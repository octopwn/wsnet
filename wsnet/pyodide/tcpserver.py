import asyncio
from inspect import trace
import os
import traceback
import typing
import io
from wsnet.protocol import *

# This object is responsible to create a binding server fusing the WSNET protocol
# Intended to be used on the browser-side

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class WSNetworkServerTCPReader:
	def __init__(self, in_queue, closed_event:asyncio.Event):
		self.wsnet_reader_type = None
		self.in_queue = in_queue
		self.closed_event = closed_event
		self.buffer = b''
		self.bufferlock = asyncio.Lock()

	async def __read_one(self):
		# will perform one read from the incoming queue
		datacmd, err = await self.in_queue.get()
		#print(err)
		#print(datacmd.data)
		if datacmd is not None and datacmd.data != b'':
			self.buffer += datacmd.data

		if err is not None:
			self.closed_event.set()
		return len(datacmd.data), err

	async def read(self, n = -1):
		try:
			#print('server connection: read %s' % n)
			if self.closed_event.is_set():
				return b''

			async with self.bufferlock:
				if n == -1:
					if len(self.buffer) == 0:
						_, err = await self.__read_one()
						if err is not None:
							raise err
					
					temp = self.buffer
					self.buffer = b''
				else:
					if len(self.buffer) == 0:
						_, err = await self.__read_one()
						if err is not None:
							raise err
					
					temp = self.buffer[:n]
					self.buffer = self.buffer[n:]
					
				#print('read ret %s' % temp)
			return temp

		except Exception as e:
			#print(e)
			self.closed_event.set()
			raise

	async def readexactly(self, n):
		try:
			#print('server connection: readexactly %s' % n)
			if self.closed_event.is_set():
				raise Exception('Pipe broken!')

			if n < 1:
				raise Exception('Readexactly must be a positive integer!')

			async with self.bufferlock:
				while len(self.buffer) < n:
					_, err = await self.__read_one()
					if err is not None:
						raise err
				
				#print('self.buffer %s' % self.buffer)
				temp = self.buffer[:n]
				self.buffer = self.buffer[n:]
				#print('readexactly ret %s' % temp)
			return temp

		except Exception as e:
			#print(e)
			self.closed_event.set()
			raise

	async def readuntil(self, separator = b'\n'):
		try:
			#print('server connection: readuntil %s' % separator)
			if self.closed_event.is_set():
				raise Exception('Pipe broken!')

			async with self.bufferlock:
				while self.buffer.find(separator) == -1:
					_, err = await self.__read_one()
					if err is not None:
						raise err
				
				end = self.buffer.find(separator)+len(separator)
				temp = self.buffer[:end]
				self.buffer = self.buffer[end:]
				#print('readuntil ret %s' % temp)
			return temp

		except Exception as e:
			#print(e)
			self.closed_event.set()
			raise

	async def readline(self):
		return await self.readuntil(b'\n')
	
	def at_eof(self):
		return self.closed_event.is_set() and len(self.buffer) == 0

class WSNetworkServerTCPWriter:
	def __init__(self, ws, token, initial_cmd, closed_event:asyncio.Event):
		self.ws = ws
		self.token = token
		self.peer_ip = initial_cmd.clientip
		self.peer_port = initial_cmd.clientport
		self.connectiontoken = initial_cmd.connectiontoken
		self.closed_event = closed_event
		self.handle_task = None
		self.__write_queue = asyncio.Queue()

	async def __writer(self):
		try:
			while not self.closed_event.is_set():
				data = await self.__write_queue.get()
				#print('sending data')
				#print(data)
				if len(data) < 286295:
					cmd = WSNServerSocketData(self.token, self.connectiontoken, data)
					js.sendWebSocketData(self.ws, cmd.to_bytes())
				else:
					# need to chunk the data because WS only accepts max 286295 bytes in one message
					data = io.BytesIO(data)
					while True:
						chunk = data.read(286200)
						if chunk == b'':
							break
						cmd = WSNServerSocketData(self.token, self.connectiontoken, chunk)
						js.sendWebSocketData(self.ws, cmd.to_bytes())
		except Exception as e:
			traceback.print_exc()
			self.closed_event.set()
			return None, e

	def write(self, data):
		if self.closed_event.is_set() is True:
			raise Exception('Connection is closed!')
		self.__write_queue.put_nowait(data)
	
	def writelines(self, data:typing.List):
		if self.closed_event.is_set() is True:
			raise Exception('Connection is closed!')
		for entry in data:
			self.write(entry)
	
	def close(self):
		self.closed_event.set()
	
	def can_write_eof(self):
		return False
	
	def write_eof(self):
		raise Exception('Not supported!')
	
	def is_closing(self):
		return self.closed_event.is_set()
	
	async def wait_closed(self):
		await self.closed_event.wait()
		
	async def drain(self):
		if self.closed_event.is_set() is True:
			raise Exception('Connection is closed!')
		return

	def get_extra_info(self, name, default = None):
		if name == 'peername':
			return (self.peer_ip, self.peer_port)
		return default

	async def run(self):
		self.handle_task = asyncio.create_task(self.__writer())
		await asyncio.sleep(0)
		return None, None

class WSNetworkServerTCPServer:
	def __init__(self, ws, token, handle_client_cb, closed_evt:asyncio.Event):
		self.ws = ws
		self.token = token
		self.closed_evt = closed_evt
		self.handle_client_cb = handle_client_cb
		self.connections = {}
		self.writers = {}
	
	async def terminate(self):
		for connectiontoken in self.writers:
			await self.writers[connectiontoken].write(b'')
		for connectiontoken in self.connections:
			await self.connections[connectiontoken].put((None, Exception('Server is terminating!')))
	
	async def serve_forever(self):
		try:
			await self.closed_evt.wait()
		except:
			self.closed_evt.set()
		
	def is_serving(self):
		return not self.closed_evt.is_set()
	
	async def wait_closed(self):
		await self.closed_evt.wait()

	async def handle_new_connection(self, cmd:WSNServerSocketData):
		try:
			# new client connected!
			print('New client connected!')
			in_q = asyncio.Queue()
			closed_event = asyncio.Event()
			reader = WSNetworkServerTCPReader(in_q, closed_event)
			writer = WSNetworkServerTCPWriter(self.ws, self.token, cmd, closed_event)
			_, err = await writer.run()
			if err is not None:
				raise err
			self.connections[cmd.connectiontoken] = in_q
			self.writers[cmd.connectiontoken] = writer
			x =  asyncio.create_task(self.handle_client_cb(reader, writer))
		except Exception as e:
			traceback.print_exc()
			

	async def handle_new_msg(self, cmd:WSNServerSocketData):
		if cmd.connectiontoken not in self.connections:
			await self.handle_new_connection(cmd)
			if cmd.data != b'':
				await self.connections[cmd.connectiontoken].put((cmd, None))
		else:
			#print('Dispatching data for existing connection')
			#print(cmd)
			await self.connections[cmd.connectiontoken].put((cmd, None))



class WSNetworkTCPServer:
	def __init__(self, handle_client_cb, ip, port, bindtype = 1, reuse_ws = False):
		self.connected_evt = None
		self.disconnected_evt = None
		self.ws_url = None
		self.ws = None
		self.ws_proxy = None
		self.ip = ip
		self.port = port
		self.reuse_ws = reuse_ws
		self.protocol = 'TCP'
		self.bindtype = bindtype
		self.handle_client_cb = handle_client_cb
		self.token = os.urandom(16)
		self.server = None
		self.closed_evt = asyncio.Event()

		self.in_task = None
		self.internal_in_q = None

	async def terminate(self):
		if self.server is not None:
			await self.server.terminate()
		if self.in_task is not None:
			self.in_task.cancel()
		if self.ws is not None:
			js.deleteWebSocket(self.ws)
		self.ws = None

	async def __handle_in(self):
		try:
			while not self.disconnected_evt.is_set():
				try:
					data_memview = await self.internal_in_q.get()
					cmd = CMD.from_bytes(bytearray(data_memview.to_py()))
					if cmd.type == CMDType.OK:
						print('Remote end terminated the server')
						raise Exception('Remote end terminated the server')
					elif cmd.type == CMDType.ERR:
						print('Proxy sent error')
						raise Exception('Proxy sent error during data transmission. Killing the tunnel.')
					elif cmd.type == CMDType.SDSRV:
						await self.server.handle_new_msg(cmd)
				except asyncio.CancelledError:
					return
				except Exception as e:
					traceback.print_exc()
					return
		finally:
			await self.terminate()

	async def connect(self):
		try:
			await asyncio.wait_for(self.connected_evt.wait(), 10)
			cmd = WSNConnect(
				self.token, 
				self.protocol, 
				self.ip, 
				self.port,
				bind = True,
				bindtype = self.bindtype
			)
			js.sendWebSocketData(self.ws, cmd.to_bytes())


			data_memview = await self.internal_in_q.get()
			cmd = CMD.from_bytes(data_memview.to_py())
			
			if cmd.type == CMDType.CONTINUE:
				return True, None
			if cmd.type == CMDType.ERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % cmd.reason)
			raise Exception('Connection failed, expected CONTINUE, got %s' % cmd.type.value)
				
		except Exception as e:
			return False, e

	async def run(self):
		try:
			self.closed_evt = asyncio.Event()
			self.connected_evt = asyncio.Event()
			self.disconnected_evt = asyncio.Event()
			self.internal_in_q = asyncio.Queue()
			connected_evt_proxy = create_proxy(self.connected_evt)
			disconnected_evt_proxy = create_proxy(self.disconnected_evt)
			data_in_proxy = create_proxy(self.internal_in_q)
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws = js.createNewWebSocket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy, self.reuse_ws, to_js(self.token)) #self.token.hex().upper()
			_, err = await self.connect()
			if err is not None:
				return False, err
			
			
			self.server = WSNetworkServerTCPServer(self.ws, self.token, self.handle_client_cb, self.closed_evt )
			self.in_task = asyncio.create_task(self.__handle_in())

			return self.server, None
		except Exception as e:
			traceback.print_exc()
			await self.terminate()
			return False, e