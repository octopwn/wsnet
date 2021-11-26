
import asyncio
import os
import traceback
import websockets
from wsnet.protocol import OPCMD, CMD, WSNOK, CMDType, WSNSocketData, WSNConnect


class WSNetworkWS:
	def __init__(self, ip, port, url, in_q, out_q, agent_id = None):
		self.ip = ip
		self.port = port
		self.url = url
		self.in_q = in_q
		self.out_q = out_q
		self.agent_id = agent_id
		self.token = os.urandom(16)
		self.ws = None
		
		self.in_task = None
		self.out_task = None

	async def terminate(self):
		if self.in_task is not None:
			self.in_task.cancel()
		if self.out_task is not None:
			self.out_task.cancel()
		if self.ws is not None:
			await self.ws.close()

	def close(self):
		if self.in_task is not None:
			self.in_task.cancel()
		if self.out_task is not None:
			self.out_task.cancel()
		if self.ws is not None:
			self.ws.close()

	async def __handle_in(self):
		while True:
			try:
				data = await self.ws.recv()
				cmd = CMD.from_bytes(data)

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
				if self.agent_id is not None:
					cmd = OPCMD(self.agent_id, cmd)
				await self.ws.send(cmd.to_bytes())
		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				if self.agent_id is not None:
					cmd = OPCMD(self.agent_id, cmd)
				await self.ws.send(cmd.to_bytes())
			except:
				pass

	async def connect(self):
		try:
			self.ws = await websockets.connect(self.url)
			cmd = WSNConnect(self.token, 'TCP', self.ip, self.port)
			print('WSNETWORKWS connect! %s' % cmd)
			if self.agent_id is not None:
				cmd = OPCMD(self.agent_id, cmd)
			

			await self.ws.send(cmd.to_bytes())
			data = await self.ws.recv()
			cmd = CMD.from_bytes(data)

			if cmd.type == CMDType.CONTINUE:
				return True, None
			if cmd.type == CMDType.ERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % cmd.reason)
			raise Exception('Connection failed, expected CONTINUE, got %s' % cmd.type.value)
				
		except Exception as e:
			traceback.print_exc()
			return False, e

	async def run(self):
		_, err = await self.connect()
		if err is not None:
			await self.in_q.put(None)
			return False, err
		
		self.in_task = asyncio.create_task(self.__handle_in())
		self.out_task = asyncio.create_task(self.__handle_out())

		return True, None