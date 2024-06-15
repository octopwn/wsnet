
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNFileData(CMD):
	def __init__(self, token, data, offset = 0):
		self.type = CMDType.FILEDATA
		self.token = token
		self.offset = offset
		self.data = data

	@staticmethod
	def from_bytes(data):
		return WSNFileData.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		offset = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		data = readBytes(buff)
		return WSNFileData(token, data, offset=offset)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		buff.write(self.offset.to_bytes(8, byteorder = 'big', signed = False))
		writeBytes(buff, self.data)
		buff.seek(0,0)
		return buff.read()