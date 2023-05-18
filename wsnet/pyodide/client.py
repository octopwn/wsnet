
import asyncio
import os
import io
import traceback
from wsnet.protocol import *

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class WSNetworkTCP:
	def __init__(self, ip, port, in_q, out_q, reuse_ws = False):
		self.connected_evt = None
		self.disconnected_evt = None
		self.ws_url = None
		self.ws = None
		self.ws_proxy = None
		self.ip = ip
		self.port = port
		self.in_q = in_q
		self.out_q = out_q
		self.reuse_ws = reuse_ws
		self.token = os.urandom(16)

		self.in_task = None
		self.out_task = None
		self.internal_in_q = None

	async def terminate(self):
		if self.in_task is not None:
			self.in_task.cancel()
		if self.out_task is not None:
			self.out_task.cancel()
		if self.ws is not None:
			js.deleteWebSocket(self.ws)
		self.ws = None

	async def __handle_in(self):
		try:
			while not self.disconnected_evt.is_set():
				try:
					data_memview = await self.internal_in_q.get()
					cmd = CMD.from_bytes(data_memview.to_py())
					if cmd.type == CMDType.OK:
						#print('Remote end terminated the socket')
						raise Exception('Remote end terminated the socket')
					elif cmd.type == CMDType.ERR:
						#print('Proxy sent error during data transmission. Killing the tunnel.')
						raise Exception('Proxy sent error during data transmission. Killing the tunnel.')

					await self.in_q.put((cmd.data, None))
				except asyncio.CancelledError:
					return
				except Exception as e:
					await self.in_q.put((None, e))
					return
		finally:
			await self.terminate()


	async def __handle_out(self):
		try:
			while not self.disconnected_evt.is_set():
				data = await self.out_q.get()
				#print('OUT %s' % data)
				if data is None or data == b'':
					return

				if len(data) < 286295:
					cmd = WSNSocketData(self.token, data)
					js.sendWebSocketData(self.ws, cmd.to_bytes())
				else:
					# need to chunk the data because WS only accepts max 286295 bytes in one message
					data = io.BytesIO(data)
					while True:
						chunk = data.read(286200)
						if chunk == b'':
							break
						cmd = WSNSocketData(self.token, chunk)
						js.sendWebSocketData(self.ws, cmd.to_bytes())

		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				js.sendWebSocketData(self.ws, cmd.to_bytes())
			except:
				pass
			await self.terminate()
	
	async def connect(self):
		try:
			await asyncio.wait_for(self.connected_evt.wait(), 10)
			cmd = WSNConnect(self.token, 'TCP', self.ip, self.port)
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
				await self.in_q.put(None)
				return False, err
			
			self.in_task = asyncio.create_task(self.__handle_in())
			self.out_task = asyncio.create_task(self.__handle_out())

			return True, None
		except Exception as e:
			await self.terminate()
			return False, e