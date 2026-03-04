
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


class WSNETWSInterface:
	def __init__(self):
		self.onDataProxy = None
		self.onErrorProxy = None
		self.onOpenProxy = None
		self.onCloseProxy = None
		self.websocketObject = None
		self.connection_established_evt = asyncio.Event()
		self.dispatch_table = {}

		self.createWebsocketObject()
	
	def createWebsocketObject(self):
		try:
			self.onOpenProxy = create_proxy(self.onOpen)
			self.onCloseProxy = create_proxy(self.onClose)
			self.onErrorProxy = create_proxy(self.onError)
			self.onDataProxy = create_proxy(self.onData)
			self.websocketObject = js.createWSNETWebSocket(self.onOpenProxy, self.onDataProxy, self.onCloseProxy, self.onErrorProxy)
			return True, None
		except Exception as e:
			traceback.print_exc()
			return False, e

	def onOpen(self):
		try:
			print('Browser WebSocket OPENED')
			self.connection_established_evt.set()
		except Exception as e:
			traceback.print_exc()
			return

	def onClose(self):
		try:
			print('Browser WebSocket CLOSED')
			self.connection_established_evt.clear()
		except Exception as e:
			traceback.print_exc()
			return
	
	def onError(self, error):
		try:
			print('Browser WebSocket ERROR: %s' % error)
			self.connection_established_evt.clear()
		except Exception as e:
			traceback.print_exc()
			return

	def onData(self, data):
		try:
			if data is None:
				return
			
			cmd = CMD.from_bytes(data.to_py())
			#print('DATA IN: %s' % cmd.type)
			if cmd.token in self.dispatch_table:
				self.dispatch_table[cmd.token](cmd)
			else:
				# this should not happen, but if it does, we need to send a OK to the remote end
				# simulating a connection close
				asyncio.create_task(self.sendCmd(WSNOK(cmd.token)))
		except Exception as e:
			traceback.print_exc()
			return
	
	def terminate(self):
		if self.onOpenProxy is not None:
			self.onOpenProxy.destroy()
			self.onOpenProxy = None
		if self.onCloseProxy is not None:
			self.onCloseProxy.destroy()
			self.onCloseProxy = None
		if self.onErrorProxy is not None:
			self.onErrorProxy.destroy()
			self.onErrorProxy = None
		if self.onDataProxy is not None:
			self.onDataProxy.destroy()
			self.onDataProxy = None
		if self.websocketObject is not None:
			self.websocketObject.close()
			self.websocketObject = None
		for token in self.dispatch_table:
			# sending a fake OK to all connections to simulate a connection close
			# as the actual ws connection has terminated
			self.dispatch_table[token](WSNOK(token))
		
	async def sendSocketData(self, token:str, data:bytes):
		try:
			if not self.connection_established_evt.is_set():
				await asyncio.wait_for(self.connection_established_evt.wait(), timeout=10)
			if data is None or data == b'':
				return

			if len(data) < 286295:
				cmd = WSNSocketData(token, data)
				rawdata = to_js(cmd.to_bytes())
				self.websocketObject.send(rawdata);
			else:
				# need to chunk the data because WS only accepts max 286295 bytes in one message
				data = io.BytesIO(data)
				while True:
					chunk = data.read(286200)
					if chunk == b'':
						break
					cmd = WSNSocketData(token, chunk)
					rawdata = to_js(cmd.to_bytes())
					self.websocketObject.send(rawdata);
			
			return True, None
		except Exception as e:
			traceback.print_exc()
			return False, e

	async def sendCmd(self, cmd:CMD):
		try:
			if not self.connection_established_evt.is_set():
				await asyncio.wait_for(self.connection_established_evt.wait(), timeout=10)
			rawdata = to_js(cmd.to_bytes())
			self.websocketObject.send(rawdata);
			return True, None
		except Exception as e:
			traceback.print_exc()
			return False, e

	async def registerConnection(self, cmd, onDataReceived):
		try:
			token = os.urandom(16)
			cmd.token = token
			self.dispatch_table[token] = onDataReceived
			await self.sendCmd(cmd)
			return token, None
		except Exception as e:
			traceback.print_exc()
			return None, e

	async def deregisterConnection(self, token):
		try:
			if token in self.dispatch_table:
				del self.dispatch_table[token]
			return True, None
		except Exception as e:
			traceback.print_exc()
			return False, e


WSNET_INTERFACE = WSNETWSInterface()