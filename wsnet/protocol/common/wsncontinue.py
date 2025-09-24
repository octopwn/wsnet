import io

from wsnet.protocol.utils import readStr, writeStr
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD

class WSNContinue(CMD):
	def __init__(self, token, msg = ""):
		self.type = CMDType.CONTINUE
		self.token = token
		self.msg = msg
	
	@staticmethod
	def from_bytes(data):
		return WSNContinue.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		msg = readStr(buff)
		return WSNContinue(token, msg = msg)
	
	def to_data(self):
		buff = io.BytesIO()
		buff.write(self.type.value.to_bytes(2, byteorder = 'big', signed = False))
		if isinstance(self.token, str):
			buff.write(self.token.encode())
		else:
			buff.write(self.token)
		if self.msg is not None:
			writeStr(buff, self.msg)
		buff.seek(0,0)
		t = buff.read()
		return t
