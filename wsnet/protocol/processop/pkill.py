
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNProcessKill(CMD):
	def __init__(self, token, pid):
		self.type = CMDType.PROCKILL
		self.token = token
		self.pid = pid

	@staticmethod
	def from_bytes(data):
		return WSNProcessKill.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		pid = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		return WSNProcessKill(token, pid)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		buff.write(self.pid.to_bytes(8, byteorder = 'big', signed = False))
		buff.seek(0,0)
		return buff.read()