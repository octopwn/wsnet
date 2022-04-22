import asyncio
import os
import traceback
from wsnet.protocol import *

try:
	import js
	from pyodide import to_js, create_proxy
except:
	pass

class WSNETClientInfo:
	def __init__(self):
		self.token = os.urandom(16)
		self.reuse_ws = True
		self.connected_evt = None
		self.disconnected_evt = None
		self.__internal_in_q = None
		self.ws = None
		self.ws_url = None
	
	def set_connected_evt(self, *args):
		self.connected_evt.set()
	
	def set_disconnected_evt(self, *args):
		self.disconnected_evt.set()
	
	def data_in(self, data):
		try:
			self.__internal_in_q.put_nowait((data, None))
		except Exception as e:
			js.console.log(str(e))

	def data_in_evt(self, event):
		self.data_in(event.data.arrayBuffer())

	async def disconnect(self):
		return

	async def get_info(self):
		try:
			self.connected_evt = asyncio.Event()
			self.disconnected_evt = asyncio.Event()
			self.__internal_in_q = asyncio.Queue()
			connected_evt_proxy = create_proxy(self.set_connected_evt)
			disconnected_evt_proxy = create_proxy(self.set_disconnected_evt)
			data_in_proxy = create_proxy(self.data_in_evt)
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws = js.createNewWebSocket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy, self.reuse_ws, to_js(self.token))
			cmd = WSNGetInfo(self.token)
			#print(cmd.to_bytes())
			await asyncio.wait_for(self.connected_evt.wait(), 5)
			js.sendWebSocketData(self.ws, to_js(cmd.to_bytes()))
			
			while True:
				x = await asyncio.wait_for( self.__internal_in_q.get(), 5)
				datapromise, err = x
				if err is not None:
					raise err
				data_memview = await datapromise
				data = data_memview.to_py()
				cmd = CMD.from_bytes(bytearray(data))
				if cmd.type == CMDType.ERR:
					return None, Exception(cmd.reason)
				elif cmd.type == CMDType.OK:
					return None, None
				elif cmd.type == CMDType.GETINFOREPLY:
					return cmd, None
		
		except Exception as e:
			return None, e
		finally:
			if self.ws is not None:
				js.deleteWebSocket(self.ws)
