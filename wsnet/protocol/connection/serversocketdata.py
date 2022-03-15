import io

from wsnet.utils.encoder import UniversalEncoder
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
import ipaddress

class WSNServerSocketData(CMD):
	def __init__(self, token, connectiontoken, data, clientip = '', clientport = 0):
		self.type = CMDType.SDSRV
		self.token = token
		self.connectiontoken = connectiontoken
		self.data = data
		self.ipver = None
		self.clientip = clientip #UDP
		self.clientport = clientport #UDP
	
	@staticmethod
	def from_bytes(data):
		return WSNServerSocketData.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		connectiontoken = buff.read(16)
		ipver = buff.read(1)
		if ipver == b'\x04':
			clientip = str(ipaddress.ip_address(buff.read(4)))
		elif ipver == b'\x06':
			clientip = str(ipaddress.ip_address(buff.read(16)))
		elif ipver == b'\xFF':
			iplen = int.from_bytes(buff.read(4), byteorder='big', signed=False)
			clientip = buff.read(iplen).decode()
		clientport = int.from_bytes(buff.read(2), byteorder='big', signed=False)
		data = buff.read(-1)
		return WSNServerSocketData(token, connectiontoken, data, clientip=clientip, clientport=clientport)

	def to_data(self):
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		if isinstance(self.connectiontoken, str):
			t += self.connectiontoken.encode()
		else:
			t += self.connectiontoken
		
		try:
			clientip = ipaddress.ip_address(self.clientip)
		except:
			t += b'\xFF' + len(self.clientip).to_bytes(4, byteorder='big', signed = False) + self.ip.encode()
		else:
			if clientip.version == 4:
				t += b'\x04' + clientip.packed
			elif clientip.version == 6:
				t += b'\x06' + clientip.packed
			else:
				raise Exception('?')
		t += self.clientport.to_bytes(2, byteorder = 'big', signed = False)
		t += self.data
		return t