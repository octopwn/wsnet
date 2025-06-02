
import io
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *
from datetime import datetime, timedelta


class WSNProcessInfo(CMD):
	def __init__(self, token, pid, name, window_title, binpath, memory_usage, thread_count, start_time, cpu_time, is_responding, main_window_title):
		self.type = CMDType.PROCINFO
		self.token = token
		self.pid = pid
		self.name = name
		self.window_title = window_title
		self.binpath = binpath
		self.memory_usage = memory_usage
		self.thread_count = thread_count
		self.start_time = start_time
		self.cpu_time = cpu_time
		self.is_responding = is_responding
		self.main_window_title = main_window_title

	@staticmethod
	def from_bytes(data):
		return WSNProcessInfo.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		pid = int.from_bytes(buff.read(8), byteorder='big', signed = False)
		name = readStr(buff)
		window_title = readStr(buff)
		binpath = readStr(buff)
		memory_usage = int.from_bytes(buff.read(8), byteorder='big', signed = False)
		thread_count = int.from_bytes(buff.read(8), byteorder='big', signed = False)
		start_time = int.from_bytes(buff.read(8), byteorder='big', signed = False)
		cpu_time = int.from_bytes(buff.read(8), byteorder='big', signed = False)
		is_responding = bool(buff.read(1)[0])
		main_window_title = readStr(buff)
		return WSNProcessInfo(token, pid, name, window_title, binpath, memory_usage, thread_count, start_time, cpu_time, is_responding, main_window_title)

	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		
		buff.write(self.pid.to_bytes(8, byteorder = 'big', signed = False))
		writeStr(buff, self.name)
		writeStr(buff, self.window_title)
		writeStr(buff, self.binpath)
		buff.write(self.memory_usage.to_bytes(8, byteorder = 'big', signed = False))
		buff.write(self.thread_count.to_bytes(8, byteorder = 'big', signed = False))
		buff.write(int(self.start_time.timestamp()).to_bytes(8, byteorder = 'big', signed = False) if self.start_time else b'\x00' * 8)
		buff.write(int(self.cpu_time.total_seconds()).to_bytes(8, byteorder = 'big', signed = False) if self.cpu_time else b'\x00' * 8)
		buff.write(b'\x01' if self.is_responding else b'\x00')
		writeStr(buff, self.main_window_title)
		# Reset buffer position to the beginning
		buff.seek(0,0)
		return buff.read()