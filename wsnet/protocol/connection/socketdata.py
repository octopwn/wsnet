import io

from wsnet.utils.encoder import UniversalEncoder
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD

class WSNSocketData(CMD):
	def __init__(self, token, data):
		self.type = CMDType.SD
		self.token = token
		self.data = data
	
	@staticmethod
	def from_bytes(data):
		return WSNSocketData.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		data = buff.read(-1)
		return WSNSocketData(token, data)

	def to_data(self):
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		t += self.data
		return t