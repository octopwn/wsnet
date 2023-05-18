import asyncio
from inspect import trace
import os
import traceback
import typing

import websockets
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
		self.data_in_evt = asyncio.Event()
		self.err = None
		self.bufferlock = asyncio.Lock()

	async def __handle_in(self):
		while True:
			res, self.err = await self.in_queue.get()
			if self.err is not None:
				if res is not None and res != b'':
					self.buffer += res.data
					self.data_in_evt.set()
				self.closed_event.set()
				return

			self.buffer += res
			self.data_in_evt.set()
			self.closed_event.set()

	async def run(self):
		self.handle_task = asyncio.create_task(self.__handle_in())
		await asyncio.sleep(0) #making sure prev line fired

	async def read(self, n = -1):
		try:
			#print('read')
			if self.closed_event.is_set():
				return b''

			async with self.bufferlock:
				if n == -1:
					if len(self.buffer) == 0:
						self.data_in_evt.clear()
						self.data_in_evt.wait()


					temp = self.buffer
					self.buffer = b''
				else:
					if len(self.buffer) == 0:
						self.data_in_evt.clear()
						self.data_in_evt.wait()
					
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
			if self.closed_event.is_set():
				raise Exception('Pipe broken!')

			if n < 1:
				raise Exception('Readexactly must be a positive integer!')

			async with self.bufferlock:
				while len(self.buffer) < n:
					self.data_in_evt.clear()
					self.data_in_evt.wait()
				
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
			if self.closed_event.is_set():
				raise Exception('Pipe broken!')

			async with self.bufferlock:
				while self.buffer.find(separator) == -1:
					self.data_in_evt.clear()
					self.data_in_evt.wait()
				
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
	def __init__(self, ws, token, connectiontoken, closed_event:asyncio.Event):
		self.ws = ws
		self.token = token
		self.connectiontoken = connectiontoken
		self.closed_event = closed_event
		self.__write_queue = asyncio.Queue()
		self.handle_task = None

	async def __writer(self):
		while not self.closed_event.is_set():
			data = await self.__write_queue.get()
			data = WSNServerSocketData(self.token, self.connectiontoken, data)
			await self.ws.send(data.to_bytes())

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
		return default

	async def run(self):
		self.handle_task = asyncio.create_task(self.__writer())
		await asyncio.sleep(0)

class WSNetworkServerTCPServer:
	def __init__(self, ws, token, handle_client_cb, closed_evt:asyncio.Event):
		self.ws = ws
		self.token = token
		self.closed_evt = closed_evt
		self.sockets = []
		self.handle_client_cb = handle_client_cb
		self.connections = {}
	
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
			in_q = asyncio.Queue()
			closed_event = asyncio.Event()
			reader = WSNetworkServerTCPReader(in_q, closed_event)
			_, err = await reader.run()
			if err is not None:
				raise err
			writer = WSNetworkServerTCPWriter(self.ws, self.token, cmd.connectiontoken, closed_event)
			_, err = await writer.run()
			if err is not None:
				raise err
			self.connections[cmd.connectiontoken] = in_q
			x =  asyncio.create_task(self.handle_client_cb(reader, writer))
		except Exception as e:
			traceback.print_exc()
			

	async def handle_new_msg(self, cmd:WSNServerSocketData):
		if cmd.connectiontoken not in self.connections:
			await self.handle_new_connection(cmd)
		else:
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
						self.server.handle_new_msg(cmd)
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