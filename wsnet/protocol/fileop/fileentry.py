
import io
import os
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *

class WSNFileEntry(CMD):
	def __init__(self, token, root, name, is_dir, size = 0, atime = 0, mtime = 0, ctime = 0):
		self.type = CMDType.FILEENTRY
		self.token = token
		self.root = root
		self.name = name
		self.is_dir = is_dir
		self.size = size
		self.atime = atime
		self.mtime = mtime
		self.ctime = ctime
		
	@staticmethod
	def from_bytes(data):
		return WSNFileEntry.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		root = readStr(buff)
		name = readStr(buff)
		is_dir = bool(buff.read(1)[0])
		size = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		atime = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		mtime = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		ctime = int.from_bytes(buff.read(8), byteorder = 'big', signed = False)
		return WSNFileEntry(token, root, name, is_dir, size, atime, mtime, ctime)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeStr(buff, self.root)
		writeStr(buff, self.name)
		buff.write(b'\x01' if self.is_dir else b'\x00')
		buff.write(self.size.to_bytes(8, byteorder = 'big', signed = False))
		buff.write(self.atime.to_bytes(8, byteorder = 'big', signed = False))
		buff.write(self.mtime.to_bytes(8, byteorder = 'big', signed = False))
		buff.write(self.ctime.to_bytes(8, byteorder = 'big', signed = False))        
		buff.seek(0,0)
		return buff.read()
	
	def to_dict(self):
		return {
			'root': self.root,
			'name': self.name,
			'is_dir': self.is_dir,
			'fullpath': self.fullpath(),
			'size': self.size,
			'atime': self.atime,
			'mtime': self.mtime,
			'ctime': self.ctime
		}
	
	def fullpath(self, separator='/'):
		return os.path.join(self.root, self.name)
	
	def __str__(self):
		return f"{self.fullpath()}{'/' if self.is_dir else ''} {self.size} {self.atime} {self.mtime} {self.ctime}"