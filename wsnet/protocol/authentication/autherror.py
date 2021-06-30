
import ipaddress
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNAuthError(CMD):
	def __init__(self, token, status, msg):
		self.type = CMDType.AUTHERR
		self.token = token
		self.status = status
		self.msg = msg

	def get_details(self):
		return "Status: %s Message: %s" % (self.status, self.msg)

	@staticmethod
	def from_bytes(data):
		return WSNAuthError.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		status = readStr(buff)
		msg = readStr(buff)
		return WSNAuthError(token, status, msg)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.status)
		writeStr(buff, self.msg)
		buff.seek(0,0)		
		return buff.read()