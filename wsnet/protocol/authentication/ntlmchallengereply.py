
import ipaddress
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNNTLMChallengeReply(CMD):
	def __init__(self, token, status, ctxattr, authdata):
		self.type = CMDType.NTLMCHALLREPLY
		self.token = token
		self.status = status
		self.ctxattr = ctxattr
		self.authdata = authdata

	@staticmethod
	def from_bytes(data):
		return WSNNTLMChallengeReply.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		status = readStr(buff)
		ctxattr = int(readStr(buff))
		authdata = readBytes(buff)
		return WSNNTLMChallengeReply(token, status, ctxattr, authdata)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.status)
		writeStr(buff, self.ctxattr)
		writeBytes(buff, self.authdata)
		buff.seek(0,0)		
		return buff.read()