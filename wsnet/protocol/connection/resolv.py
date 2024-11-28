
from typing import List
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import readStr, writeStr

class WSNResolv(CMD):
	def __init__(self, token, ip_or_hostnames:List[str]):
		self.type = CMDType.RESOLV
		self.token = token
		self.count = len(ip_or_hostnames)
		self.ip_or_hostnames = ip_or_hostnames

	@staticmethod
	def from_bytes(data):
		return WSNResolv.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		count = int.from_bytes(buff.read(4), byteorder = 'big', signed = False)
		ip_or_hostnames = []
		for _ in range(count):
			ip_or_hostnames.append(readStr(buff))
		return WSNResolv(token, ip_or_hostnames)

	def to_data(self):
		t = io.BytesIO()
		t.write(self.type.value.to_bytes(2, byteorder = 'big', signed = False))
		if isinstance(self.token, str):
			t.write(self.token.encode())
		else:
			t.write(self.token)
		t.write(self.count.to_bytes(4, byteorder = 'big', signed = False))
		for ip_or_hostname in self.ip_or_hostnames:
			writeStr(t, ip_or_hostname)
		t.seek(0)
		return t.read()