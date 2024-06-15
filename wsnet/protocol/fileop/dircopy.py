
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNDirCopy(CMD):
	def __init__(self, token, srcpath, dstpath):
		self.type = CMDType.DIRCOPY
		self.token = token
		self.srcpath = srcpath
		self.dstpath = dstpath

	@staticmethod
	def from_bytes(data):
		return WSNDirCopy.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		srcpath = readStr(buff)
		dstpath = readStr(buff)
		return WSNDirCopy(token, srcpath, dstpath)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.srcpath)
		writeStr(buff, self.dstpath)
		buff.seek(0,0)
		return buff.read()