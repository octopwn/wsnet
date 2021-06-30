import asyncio
import os
import traceback
import websockets
from wsnet.protocol import OPCMD, CMD, CMDType, WSNGetSequenceNo, WSNGetSessionKey,\
	WSNNTLMChallenge, WSNNTLMAuth, WSNKerberosAuth


class WSNETSSPIProxy:
	"""
	Helper class to perform SSPI authentication remotely on an agent (via the router)
	Currently it supports NTLM and Kerberos authentication
	"""
	def __init__(self, url, agentid = None):
		self.url = url
		self.agentid = agentid # if agentid is none then we are talking with the c2, otherwise it's a direct connection
		self.token = os.urandom(16)
		self.iter = 0
		self.ws = None
		self.timeout = 10

	async def disconnect(self):
		if self.ws is not None:
			asyncio.create_task(self.ws.close())
		return

	async def setup(self):
		try:
			self.ws = await websockets.connect(self.url, close_timeout=1)
			return True, None
		except Exception as e:
			return False, e

	async def sr(self, cmd):
		try:
			if self.agentid is not None:
				cmd = OPCMD(self.agentid, cmd)

			while True:
				await asyncio.wait_for(self.ws.send(cmd.to_bytes()), timeout = self.timeout)
				reply_raw = await self.ws.recv()
				reply = CMD.from_bytes(reply_raw)
				if reply.token == b'\x00'*16:
					continue
				if reply.type == CMDType.ERR:
					raise Exception("Reason: %s Extra: %s" % (reply.reason, reply.extra))
				break

			return reply, None
		except Exception as e:
			return None, e


	async def get_sequenceno(self):
		try:
			if self.ws is None:
				_, err = await self.setup()
				if err is not None:
					raise err

			cmd = WSNGetSequenceNo(self.token)
			#print(cmd.to_bytes())
			reply, err = await self.sr(cmd)
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
			if self.ws is None:
				_, err = await self.setup()
				if err is not None:
					raise err

			cmd = WSNGetSessionKey(self.token)
			reply, err = await self.sr(cmd)
			if err is not None:
				raise err

			if reply.type == CMDType.AUTHERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
			
			return reply.sessionkey, None
		
		except Exception as e:
			return None, e

	async def authenticate(self, auth_type, username, target, credusage, flags, authdata):
		try:
			if self.ws is None:
				_, err = await self.setup()
				if err is not None:
					raise err

			if auth_type.upper() == 'KERBEROS':
				cmd = WSNKerberosAuth(self.token, target, username, credusage, flags, authdata)
				reply, err = await self.sr(cmd)
				if err is not None:
					raise err
				if reply.type == CMDType.AUTHERR:
					raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
				
				self.iter += 1

				return reply.status, reply.ctxattr, reply.authdata, None

			elif auth_type.upper() == 'NTLM':
				if self.iter == 0:
					cmd = WSNNTLMAuth(self.token, username, credusage, flags, target)
					reply, err = await self.sr(cmd)
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				elif self.iter == 1:
					cmd = WSNNTLMChallenge(self.token, authdata, flags, target)
					reply, err = await self.sr(cmd)
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				else:
					raise Exception('Too many tiers for NTLM!')
		except Exception as e:
			return None, None, None, e