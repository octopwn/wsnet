import asyncio
import os
import traceback
import typing
from wsnet.protocol import *

# This object is responsible to create a binding server fusing the WSNET protocol
# Intended to be used on the browser-side

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class FakeSocket:
	def __init__(self, ip, port):
		self.ip = ip
		self.port = port

	def getpeername(self):
		return (str(self.ip), int(self.port))
	
class WSNetworkServerUDPReader:
	def __init__(self, token, connectiontoken, in_q):
		self.token = token
		self.connectiontoken = connectiontoken
		self.in_q = in_q

class WSNetworkServerUDPWriter:
	def __init__(self, ws, token, connectiontoken, ip, port):
		self.ws = ws
		self.token = token
		self.connectiontoken = connectiontoken
		self.ip = ip
		self.port = port

	def get_extra_info(self, infotype):
		if infotype == "socket":
			return FakeSocket(self.ip, self.port)

	async def sendto(self, data, addr):
		data = WSNServerSocketData(self.token, self.connectiontoken, data, addr[0], addr[1])
		await self.ws.send(data.to_bytes())

class WSNetworkUDPServer:
	def __init__(self, transportfactory, ip, port, bindtype = 1, reuse_ws = False):
		self.connected_evt = None
		self.disconnected_evt = None
		self.ws_url = None
		self.ws = None
		self.ws_proxy = None
		self.ip = ip
		self.port = port
		self.reuse_ws = reuse_ws
		self.protocol = 'UDP'
		self.bindtype = bindtype
		self.transportfactory = transportfactory
		self.token = os.urandom(16)
		self.connectiontoken = '1'*16

		self.in_task = None
		self.out_task = None
		self.__internal_in_q = None
		self.connections = {} # clinettoken -> 
		self.client_tasks = {} # clienttoken = client_task

		self.transport = None
		

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
						print('Remote end terminated the socket')
						raise Exception('Remote end terminated the socket')
					elif cmd.type == CMDType.ERR:
						print('Proxy sent error during data transmission. Killing the tunnel.')
						raise Exception('Proxy sent error during data transmission. Killing the tunnel.')
					elif cmd.type == CMDType.SDSRV:
						cmd = typing.cast(WSNServerSocketData, cmd)
						self.transport.datagram_received(cmd.data, (cmd.clientip, cmd.clientport))
				except asyncio.CancelledError:
					return
				except Exception as e:
					traceback.print_exc()
					self.transport.datagram_received(b'', (None, None))
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
				self.transport = self.transportfactory()
				self.writer = WSNetworkServerUDPWriter(self.ws, self.token, self.connectiontoken, self.ip, self.port)
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
				raise err
			
			self.in_task = asyncio.create_task(self.__handle_in())

			return self.writer, self.transport, None
		except Exception as e:
			await self.terminate()
			return None, None, e