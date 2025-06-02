
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNProcessList(CMD):
	def __init__(self, token):
		self.type = CMDType.PROCLIST
		self.token = token

	@staticmethod
	def from_bytes(data):
		return WSNProcessList.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		return WSNProcessList(token)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		buff.seek(0,0)
		return buff.read()