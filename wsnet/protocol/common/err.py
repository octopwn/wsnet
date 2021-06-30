import io

from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD

class WSNErr(CMD):
	def __init__(self, token, reason, extra = ''):
		self.type = CMDType.ERR
		self.token = token
		self.reason = reason
		self.extra = extra
	
	@staticmethod
	def from_bytes(data):
		return WSNErr.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		length = int.from_bytes(buff.read(4), byteorder='big', signed=False)
		reason = buff.read(length).decode()
		length = int.from_bytes(buff.read(4), byteorder='big', signed=False)
		extra = buff.read(length).decode()

		return WSNErr(token, reason, extra)
	
	def to_data(self):
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token

		t += len(self.reason).to_bytes(4, byteorder='big', signed=False)
		t += self.reason.encode()
		t += len(self.extra).to_bytes(4, byteorder='big', signed=False)
		t += self.extra.encode()

		return t