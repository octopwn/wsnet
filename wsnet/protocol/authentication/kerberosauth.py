
import ipaddress
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNKerberosAuth(CMD):
	def __init__(self, token, targetname, username = "", credusage = 3, ctxattr = 0, authdata = b''):
		self.type = CMDType.KERBEROS
		self.token = token
		self.username = username
		self.credusage = credusage
		self.ctxattr = ctxattr
		self.targetname = targetname
		self.authdata = authdata

	@staticmethod
	def from_bytes(data):
		return WSNKerberosAuth.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		username = readStr(buff)
		credusage = int(readStr(buff))
		ctxattr = int(readStr(buff))
		targetname = readStr(buff)
		authdata = readBytes(buff)
		return WSNKerberosAuth(token, targetname, username, credusage, ctxattr, authdata)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.username)
		writeStr(buff, self.credusage)
		writeStr(buff, self.ctxattr)
		writeStr(buff, self.targetname)
		writeBytes(buff, self.authdata)
		buff.seek(0,0)		
		return buff.read()