
import asyncio
import os
import traceback
from wsnet.protocol import *

try:
	import js
	from pyodide import to_js, create_proxy
except:
	pass

class WSNetworkTCP:
	def __init__(self, ip, port, in_q, out_q):
		self.connected_evt = None
		self.disconnected_evt = None
		self.ws_url = None
		self.ws = None
		self.ws_proxy = None
		self.ip = ip
		self.port = port
		self.in_q = in_q
		self.out_q = out_q
		self.token = os.urandom(16)

		self.in_task = None
		self.out_task = None
		self.__internal_in_q = None

	async def terminate(self):
		if self.in_task is not None:
			self.in_task.cancel()
		if self.out_task is not None:
			self.out_task.cancel()
	
	def data_in(self, data):
		try:
			self.__internal_in_q.put_nowait((data, None))
		except Exception as e:
			js.console.log(str(e))
	
	def set_connected_evt(self, *args):
		self.connected_evt.set()
	
	def set_disconnected_evt(self, *args):
		self.disconnected_evt.set()

	def data_in_evt(self, event):
		self.data_in(event.data.arrayBuffer())

	async def __handle_in(self):
		while not self.disconnected_evt.is_set():
			try:
				datapromise, err = await self.__internal_in_q.get()
				data_memview = await datapromise
				data = data_memview.to_py()
				cmd = CMD.from_bytes(bytearray(data))

				#print('__handle_in %s' % cmd)
				if err is not None:
					raise err
				if cmd.type == CMDType.OK:
					print('Remote end terminated the socket')
					raise Exception('Remote end terminated the socket')
				elif cmd.type == CMDType.ERR:
					print('Proxy sent error during data transmission. Killing the tunnel.')
					raise Exception('Proxy sent error during data transmission. Killing the tunnel.')

				await self.in_q.put((cmd.data, None))
			except asyncio.CancelledError:
				return
			except Exception as e:
				traceback.print_exc()
				await self.in_q.put((None, e))
				return


	async def __handle_out(self):
		try:
			while not self.disconnected_evt.is_set():
				data = await self.out_q.get()
				#print('OUT %s' % data)
				if data is None or data == b'':
					return
				cmd = WSNSocketData(self.token, data)
				#self.ws.send(to_js(cmd.to_bytes()))
				js.sendWebScoketData(self.ws, to_js(cmd.to_bytes()))
		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				js.sendWebScoketData(self.ws, to_js(cmd.to_bytes()))
			except:
				pass
	
	async def connect(self):
		try:
			await asyncio.wait_for(self.connected_evt.wait(), 10)
			cmd = WSNConnect(self.token, 'TCP', self.ip, self.port)
			js.sendWebScoketData(self.ws, to_js(cmd.to_bytes()))


			datapromise, err = await self.__internal_in_q.get()
			data_memview = await datapromise
			data = data_memview.to_py()

			cmd = CMD.from_bytes(bytearray(data))

			#print('connect %s' % cmd)
			if err is not None:
				raise err
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
			self.__internal_in_q = asyncio.Queue()
			connected_evt_proxy = create_proxy(self.set_connected_evt)
			disconnected_evt_proxy = create_proxy(self.set_disconnected_evt)
			data_in_proxy = create_proxy(self.data_in_evt)
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws = js.createNewWebScoket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy)
			#self.ws_url = js.document.getElementById('proxyurl')
			#self.ws = js.WebSocket.new(self.ws_url.value)
			#self.ws.addEventListener('open', connected_evt_proxy)
			#self.ws.addEventListener('message', data_in_proxy)
			#self.ws_proxy = create_proxy(self.ws)

			_, err = await self.connect()
			if err is not None:
				await self.in_q.put(None)
				return False, err
			
			self.in_task = asyncio.create_task(self.__handle_in())
			self.out_task = asyncio.create_task(self.__handle_out())

			return True, None
		except Exception as e:
			return False, e