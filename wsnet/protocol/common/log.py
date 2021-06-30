import io


from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD

class WSNLog(CMD):
	def __init__(self, token, level, msg):
		self.type = CMDType.LOG
		self.token = token
		self.level = level
		self.msg = msg
	
	@staticmethod
	def from_bytes(data):
		return WSNLog.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		level = int.from_bytes(buff.read(2), byteorder='big', signed=False)
		length = int.from_bytes(buff.read(4), byteorder='big', signed=False)
		msg = buff.read(length).decode()

		return WSNLog(token, level, msg)
	
	def to_data(self):
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token

		t += self.level.to_bytes(2, byteorder='big', signed=False)
		t += len(self.msg).to_bytes(4, byteorder='big', signed=False)
		t += self.msg.encode()

		return t