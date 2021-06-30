
import asyncio
import os
import traceback
import builtins
from wsnet.protocol import *

# this is a pyodide module to access javascript objects
#from js import wsnet
#import js

class WSNetworkTCP:
	def __init__(self, ip, port, in_q, out_q):
		self.ip = ip
		self.port = port
		self.in_q = in_q
		self.out_q = out_q
		self.token = os.urandom(16)

		self.in_task = None
		self.out_task = None

	async def terminate(self):
		if self.in_task is not None:
			self.in_task.cancel()
		if self.out_task is not None:
			self.out_task.cancel()

	async def __handle_in(self):
		while True:
			try:
				cmd, err = await builtins.global_wsnet_dispatch_table[self.token].get()			
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
				await self.in_q.put((None, e))
				return


	async def __handle_out(self):
		try:
			while True:	
				data = await self.out_q.get()
				#print('OUT %s' % data)
				if data is None or data == b'':
					return
				cmd = WSNSocketData(self.token, data)
				builtins.global_current_websocket[-1].send(cmd.to_bytes())
		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				builtins.global_current_websocket[-1].send(cmd.to_bytes())
			except:
				pass

	async def connect(self):
		try:
			builtins.global_wsnet_dispatch_table[self.token] = asyncio.Queue()
			cmd = WSNConnect(self.token, 'TCP', self.ip, self.port)
			builtins.global_current_websocket[-1].send(cmd.to_bytes())
			cmd, err = await builtins.global_wsnet_dispatch_table[self.token].get()
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
		_, err = await self.connect()
		if err is not None:
			await self.in_q.put(None)
			return False, err
		
		self.in_task = asyncio.create_task(self.__handle_in())
		self.out_task = asyncio.create_task(self.__handle_out())

		return True, None