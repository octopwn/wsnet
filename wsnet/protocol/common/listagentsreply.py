
from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol import CMD
from wsnet.protocol.utils import *
import io
import json

class WSNListAgentsReply(CMD):
	def __init__(self, token, agentid, pid, username, domain, logonserver, cpuarch, hostname, usersid):
		self.type = CMDType.AGENTINFO
		self.agentid = agentid
		self.token = token
		self.pid = pid
		self.username = username
		self.domain = domain
		self.logonserver = logonserver
		self.cpuarch = cpuarch
		self.hostname = hostname
		self.usersid = usersid
	
	@staticmethod
	def from_bytes(data):
		return WSNListAgentsReply.from_buffer(io.BytesIO(data))
	
	@staticmethod
	def from_buffer(buff):
		token = buff.read(16)
		agentid = readBytes(buff)
		pid = int(readStr(buff))
		username = readStr(buff, 'utf-16-le')
		domain = readStr(buff, 'utf-16-le')
		logonserver = readStr(buff, 'utf-16-le')
		cpuarch = readStr(buff)
		hostname = readStr(buff, 'utf-16-le')
		usersid = readStr(buff)
		return WSNListAgentsReply(token, agentid, pid, username, domain, logonserver, cpuarch, hostname, usersid)
	
	def to_data(self):
		buff = io.BytesIO()
		t = self.type.value.to_bytes(2, byteorder = 'big', signed = False)
		if isinstance(self.token, str):
			t += self.token.encode()
		else:
			t += self.token
		buff.write(t)
		writeBytes(buff, self.agentid)
		writeStr(buff, str(self.pid))
		writeStr(buff, self.username, encoding='utf-16-le')
		writeStr(buff, self.domain, encoding='utf-16-le')
		writeStr(buff, self.logonserver, encoding='utf-16-le')
		writeStr(buff, self.cpuarch)
		writeStr(buff, self.hostname, encoding='utf-16-le')
		writeStr(buff, self.usersid)
		buff.seek(0,0)
		return buff.read()
	
	def to_dict(self):
		return {
			'agentid' : self.agentid.hex(),
			'pid' : self.pid,
			'username' :  self.username,
			'domain' : self.domain,
			'logonserver' : self.logonserver,
			'cpuarch' : self.cpuarch,
			'hostname' : self.hostname,
			'usersid' : self.usersid
		}

	def to_json(self):
		return json.dumps(self.to_dict())
	
	def __str__(self):
		return self.to_json()