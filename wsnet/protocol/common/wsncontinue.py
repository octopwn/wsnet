import io

from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD

class WSNContinue(CMD):
	def __init__(self, token):
		self.type = CMDType.CONTINUE
		self.token = token
	
	@staticmethod
	def from_bytes(data):
		return WSNContinue.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		return WSNContinue(token)
	
	def to_data(self):
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		return t