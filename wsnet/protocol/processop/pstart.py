
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNProcessStart(CMD):
	def __init__(self, token, command, arguments):
		self.type = CMDType.PROCSTART
		self.token = token
		self.command = command
		self.arguments = arguments

	@staticmethod
	def from_bytes(data):
		return WSNProcessStart.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		command = readStr(buff)
		arguments = readStr(buff)
		return WSNProcessStart(token, command, arguments)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.command)
		writeStr(buff, self.arguments)
		buff.seek(0,0)
		return buff.read()