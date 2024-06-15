
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNDirMK(CMD):
	def __init__(self, token, path):
		self.type = CMDType.DIRMK
		self.token = token
		self.path = path

	@staticmethod
	def from_bytes(data):
		return WSNDirMK.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		path = readStr(buff)
		return WSNDirMK(token, path)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.path)
		buff.seek(0,0)
		return buff.read()