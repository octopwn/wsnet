
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNFileOpen(CMD):
	def __init__(self, token, path, mode = 'r'):
		self.type = CMDType.FILEOPEN
		self.token = token
		self.path = path
		self.mode = mode

	@staticmethod
	def from_bytes(data):
		return WSNFileOpen.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		path = readStr(buff)
		mode = readStr(buff)
		return WSNFileOpen(token, path, mode=mode)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.path)
		writeStr(buff, self.mode)
		buff.seek(0,0)
		return buff.read()