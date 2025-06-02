
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNProcessSTD(CMD):
	def __init__(self, token, outtype, data):
		self.type = CMDType.PROCSTD
		self.token = token
		self.outtype = outtype
		self.data = data

	@staticmethod
	def from_bytes(data):
		return WSNProcessSTD.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		outtype = int.from_bytes(buff.read(4), byteorder = 'big', signed = False)
		data = readStr(buff)
		return WSNProcessSTD(token, outtype, data)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		buff.write(self.outtype.to_bytes(4, byteorder = 'big', signed = False))
		writeStr(buff, self.data)
		buff.seek(0,0)
		return buff.read()