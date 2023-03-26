import asyncio
import os
import traceback
from wsnet.protocol import *

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class WSNETClientInfo:
	def __init__(self):
		self.token = os.urandom(16)
		self.reuse_ws = True
		self.connected_evt = None
		self.disconnected_evt = None
		self.internal_in_q = None
		self.ws = None
		self.ws_url = None

	async def disconnect(self):
		return

	async def get_info(self):
		try:
			self.connected_evt = asyncio.Event()
			self.disconnected_evt = asyncio.Event()
			self.internal_in_q = asyncio.Queue()
			connected_evt_proxy = create_proxy(self.connected_evt)
			disconnected_evt_proxy = create_proxy(self.disconnected_evt)
			data_in_proxy = create_proxy(self.internal_in_q)
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws = js.createNewWebSocket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy, self.reuse_ws, to_js(self.token))
			cmd = WSNGetInfo(self.token)
			#print(cmd.to_bytes())
			await asyncio.wait_for(self.connected_evt.wait(), 5)
			js.sendWebSocketData(self.ws, cmd.to_bytes())
			
			while True:
				data_memview = await asyncio.wait_for(self.internal_in_q.get(), 5)
				cmd = CMD.from_bytes(data_memview.to_py())
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
