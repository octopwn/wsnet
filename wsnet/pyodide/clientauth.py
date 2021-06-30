import asyncio
import os
import traceback
import builtins
from wsnet.protocol import *

# this is a pyodide module to access javascript objects
#from js import wsnet
#import js

class WSNETAuth:
	def __init__(self):
		self.token = os.urandom(16)
		self.iter = 0

	async def disconnect(self):
		return

	async def setup(self):
		if self.token not in builtins.global_wsnet_dispatch_table:
			builtins.global_wsnet_dispatch_table[self.token] = asyncio.Queue()

	async def get_sequenceno(self):
		try:
			await self.setup()
			cmd = WSNGetSequenceNo(self.token)
			#print(cmd.to_bytes())
			builtins.global_current_websocket[-1].send(cmd.to_bytes())
			reply, err = await builtins.global_wsnet_dispatch_table[self.token].get()
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
			await self.setup()
			cmd = WSNGetSessionKey(self.token)
			#print(cmd.to_bytes())
			builtins.global_current_websocket[-1].send(cmd.to_bytes())
			reply, err = await builtins.global_wsnet_dispatch_table[self.token].get()
			if err is not None:
				raise err
			if reply.type == CMDType.AUTHERR:
				raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())
			
			return reply.sessionkey, None
		
		except Exception as e:
			return None, e

	async def authenticate(self, auth_type, username, target, credusage, flags, authdata):
		try:
			await self.setup()
			if auth_type.upper() == 'KERBEROS':
				cmd = WSNKerberosAuth(self.token, target, username, credusage, flags, authdata)
				#print(cmd.to_bytes())
				builtins.global_current_websocket[-1].send(cmd.to_bytes())
				reply, err = await builtins.global_wsnet_dispatch_table[self.token].get()
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
					builtins.global_current_websocket[-1].send(cmd.to_bytes())
					reply, err = await builtins.global_wsnet_dispatch_table[self.token].get()	
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				elif self.iter == 1:
					cmd = WSNNTLMChallenge(self.token, authdata, flags, target)
					#print(cmd.to_bytes())
					builtins.global_current_websocket[-1].send(cmd.to_bytes())
					reply, err = await builtins.global_wsnet_dispatch_table[self.token].get()
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