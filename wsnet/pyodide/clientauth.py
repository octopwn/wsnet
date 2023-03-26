import asyncio
import os
import traceback
import builtins
from wsnet.protocol import *

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class WSNETAuth:
	def __init__(self):
		self.connected_evt = None
		self.disconnected_evt = None
		self.internal_in_q = None
		self.ws_url = None
		self.ws = None

		self.token = os.urandom(16)
		self.iter = 0
		self.ws = None
		self.ws_url = None

	async def disconnect(self):
		return

	async def read_in(self):
		try:
			data_memview = await self.internal_in_q.get()
			cmd = CMD.from_bytes(data_memview.to_py())
			return cmd, None
		except Exception as e:
			return None, e

	async def setup(self):
		try:
			if self.ws is not None:
				return True, None
			self.connected_evt = asyncio.Event()
			self.disconnected_evt = asyncio.Event()
			self.internal_in_q = asyncio.Queue()

			connected_evt_proxy = create_proxy(self.connected_evt)
			disconnected_evt_proxy = create_proxy(self.disconnected_evt)
			data_in_proxy = create_proxy(self.internal_in_q)
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws = js.createNewWebSocket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy, True, to_js(self.token))
			await asyncio.wait_for(self.connected_evt.wait(), 5)
			return True, None
		except Exception as e:
			return None, e

	async def get_sequenceno(self):
		try:
			await self.setup()
			cmd = WSNGetSequenceNo(self.token)
			#print(cmd.to_bytes())
			js.sendWebSocketData(self.ws, cmd.to_bytes())
			reply, err = await self.read_in()
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
			js.sendWebSocketData(self.ws, cmd.to_bytes())
			reply, err = await self.read_in()
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
				js.sendWebSocketData(self.ws, cmd.to_bytes())
				reply, err = await self.read_in()
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
					js.sendWebSocketData(self.ws, cmd.to_bytes())
					reply, err = await self.read_in()
					if err is not None:
						raise err
					if reply.type == CMDType.AUTHERR:
						raise Exception('Connection failed, proxy sent error. Err: %s' % reply.get_details())

					self.iter += 1
					return reply.status, reply.ctxattr, reply.authdata, None
				
				elif self.iter == 1:
					cmd = WSNNTLMChallenge(self.token, authdata, flags, target)
					#print(cmd.to_bytes())
					js.sendWebSocketData(self.ws, cmd.to_bytes())
					reply, err = await self.read_in()
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