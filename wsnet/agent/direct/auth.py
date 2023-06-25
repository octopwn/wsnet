import asyncio
import os
from wsnet.protocol import *
import websockets


class WSNETDirectAuth:
	def __init__(self, ws_url, ssl_ctx = None, connect_timeout = 5):
		self.token = os.urandom(16)
		self.iter = 0
		self.ws = None
		self.ws_url = ws_url
		self.ssl_ctx = ssl_ctx
		self.internal_in_q = None
		self.connected_evt = None
		self.connect_timeout = connect_timeout

	async def disconnect(self):
		return
	
	async def __reader(self):
		async with websockets.connect(self.ws_url, ssl=self.ssl_ctx) as self.ws:
			self.connected_evt.set()
			while True:
				try:
					data = await self.ws.recv()
					cmd = CMD.from_bytes(data)
					await self.internal_in_q.put((cmd, None))
				except websockets.exceptions.ConnectionClosed:
					break
	
	async def connect(self):
		try:
			self.internal_in_q = asyncio.Queue()
			self.connected_evt = asyncio.Event()
			self.reader_task = asyncio.create_task(self.__reader())
			await asyncio.wait_for(self.connected_evt.wait(), self.connect_timeout)
			return True, None
		except Exception as e:
			return None, e

	async def get_sequenceno(self):
		try:
			cmd = WSNGetSequenceNo(self.token)
			#print(cmd.to_bytes())
			await self.ws.send(cmd.to_bytes())
			reply, err = await self.internal_in_q.get()
			#print('reply %s' % reply)

			if err is not None:
				raise err
			if reply.type == CMDType.AUTHERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
			
			#print('reply.encdata %s' % reply.encdata)
			return reply.encdata, None
		
		except Exception as e:
			return None, e

	async def get_sessionkey(self):
		try:
			cmd = WSNGetSessionKey(self.token)
			#print(cmd.to_bytes())
			await self.ws.send(cmd.to_bytes())
			reply, err = await self.internal_in_q.get()
			if err is not None:
				raise err
			if reply.type == CMDType.AUTHERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
			
			return reply.sessionkey, None
		
		except Exception as e:
			return None, e

	async def authenticate(self, auth_type, username, target, credusage, flags, authdata):
		try:
			if auth_type.upper() == 'KERBEROS':
				cmd = WSNKerberosAuth(self.token, target, username, credusage, flags, authdata)
				#print(cmd.to_bytes())
				await self.ws.send(cmd.to_bytes())
				reply, err = await self.internal_in_q.get()
				if err is not None:
					raise err
				if reply.type == CMDType.AUTHERR:
					raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
				
				self.iter += 1

				return reply.status, reply.ctxattr, reply.authdata, None

			elif auth_type.upper() == 'NTLM':
				if self.iter == 0:
					cmd = WSNNTLMAuth(self.token, username, credusage, flags, target)
					#print(cmd.to_bytes())
					await self.ws.send(cmd.to_bytes())
					reply, err = await self.internal_in_q.get()
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				elif self.iter == 1:
					cmd = WSNNTLMChallenge(self.token, authdata, flags, target)
					#print(cmd.to_bytes())
					await self.ws.send(cmd.to_bytes())
					reply, err = await self.internal_in_q.get()
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				else:
					raise Exception('Too many tries for NTLM!')
		except Exception as e:
			return None, None, None, e