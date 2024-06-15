
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNFileRead(CMD):
	def __init__(self, token, size, offset = 0):
		self.type = CMDType.FILEREAD
		self.token = token
		self.size = size
		self.offset = offset

	@staticmethod
	def from_bytes(data):
		return WSNFileRead.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		size = int.from_bytes(buff.read(4), byteorder = 'big', signed = False)
		offset = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		return WSNFileRead(token, size, offset=offset)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		buff.write(self.size.to_bytes(4, byteorder = 'big', signed = False))
		buff.write(self.offset.to_bytes(8, byteorder = 'big', signed = False))
		buff.seek(0,0)
		return buff.read()