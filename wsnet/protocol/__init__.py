
import enum
import io



"""

 | length(4 bytes, unsigned, byteorder big) | data_type(short) 0| DATA (length + 5)
length = total length of the "packet" including this length field

"""

class CMD:
	def __init__(self):
		self.type:CMDType = None

	def to_bytes(self):
		data = self.to_data()
		return (len(data)+4).to_bytes(4, byteorder = 'big', signed = False) + data
	
	def get_bytes(self):
		#to be implemented by child if it's a binary one
		return None

	@staticmethod
	def from_bytes(data):
		return CMD.from_buffer(io.BytesIO(data))

	@staticmethod
	def from_buffer(buff):
		length = int.from_bytes(buff.read(4), byteorder = 'big', signed = False)
		dt = int.from_bytes(buff.read(2), byteorder = 'big', signed = False)
		return type2cmd[CMDType(dt)].from_buffer(buff)

class OPCMD:
	def __init__(self, agentid, cmd):
		self.agentid = agentid
		self.cmd = cmd

	def to_bytes(self):
		t = self.agentid
		t += self.cmd.to_bytes()
		cmdlen = len(t).to_bytes(4, byteorder='big', signed = False)
		return cmdlen+t


from wsnet.protocol.cmdtypes import CMDType
from wsnet.protocol.common.ok import WSNOK
from wsnet.protocol.common.nop import WSNNOP
from wsnet.protocol.common.err import WSNErr
from wsnet.protocol.common.log import WSNLog
from wsnet.protocol.common.stop import WSNStop
from wsnet.protocol.common.stop import WSNStop
from wsnet.protocol.common.info import WSNGetInfo
from wsnet.protocol.common.inforeply import WSNGetInfoReply
from wsnet.protocol.connection.connect import WSNConnect
from wsnet.protocol.connection.socketdata import WSNSocketData
from wsnet.protocol.common.wsncontinue import WSNContinue
from wsnet.protocol.authentication.ntlmauth import WSNNTLMAuth
from wsnet.protocol.authentication.ntlmauthreply import WSNNTLMAuthReply
from wsnet.protocol.authentication.ntlmchallengereply import WSNNTLMChallengeReply
from wsnet.protocol.authentication.ntlmchallenge import WSNNTLMChallenge
from wsnet.protocol.authentication.sessionkey import WSNGetSessionKey
from wsnet.protocol.authentication.sessionkeyreply import WSNSessionKeyReply
from wsnet.protocol.authentication.kerberosauth import WSNKerberosAuth
from wsnet.protocol.authentication.kerberosauthreply import WSNKerberosAuthReply
from wsnet.protocol.authentication.autherror import WSNAuthError
from wsnet.protocol.authentication.sequenceno import WSNGetSequenceNo
from wsnet.protocol.authentication.sequencenoreply import WSNGetSequenceNoReply
from wsnet.protocol.common.listagents import WSNListAgents
from wsnet.protocol.common.listagentsreply import WSNListAgentsReply
from wsnet.protocol.connection.serversocketdata import WSNServerSocketData
from wsnet.protocol.connection.wrapssl import WSNSocketWrapSSL



__all__ = [
	'CMDType',
	'CMD',
	'OPCMD',
	'WSNOK',
	'WSNNOP',
	'WSNErr',
	'WSNLog',
	'WSNContinue',
	'WSNStop',
	'WSNConnect',
	'WSNSocketData',
	'WSNNTLMAuth',
	'WSNNTLMAuthReply',
	'WSNNTLMChallenge',
	'WSNNTLMChallengeReply',
	'WSNGetSessionKey',
	'WSNSessionKeyReply',
	'WSNKerberosAuthReply',
	'WSNKerberosAuth',
	'WSNAuthError',
	'WSNGetSequenceNo',
	'WSNGetSequenceNoReply',
	'WSNGetInfoReply',
	'WSNGetInfo',
	'WSNListAgents',
	'WSNListAgentsReply',
	'WSNServerSocketData',
	'WSNSocketWrapSSL'

]

BINARY_TYPES = [
	CMDType.SD,
]

type2cmd = {
	CMDType.OK : WSNOK,
	CMDType.NOP : WSNNOP,
	CMDType.ERR : WSNErr,
	CMDType.LOG : WSNLog,
	CMDType.CONTINUE : WSNContinue,
	CMDType.STOP : WSNStop,
	CMDType.CONNECT : WSNConnect,
	CMDType.SD : WSNSocketData,
	CMDType.NTLMAUTH : WSNNTLMAuth,
	CMDType.NTLMAUTHREPLY : WSNNTLMAuthReply,
	CMDType.NTLMCHALL : WSNNTLMChallenge,
	CMDType.NTLMCHALLREPLY : WSNNTLMChallengeReply,
	CMDType.SESSIONKEY : WSNGetSessionKey,
	CMDType.SESSIONKEYREPLY : WSNSessionKeyReply,
	CMDType.KERBEROS : WSNKerberosAuth,
	CMDType.KERBEROSREPLY : WSNKerberosAuthReply,
	CMDType.AUTHERR : WSNAuthError,
	CMDType.SEQUENCE : WSNGetSequenceNo,
	CMDType.SEQUENCEREPLY : WSNGetSequenceNoReply,
	CMDType.GETINFO : WSNGetInfo,
	CMDType.GETINFOREPLY : WSNGetInfoReply,
	CMDType.LISTAGENTS : WSNListAgents,
	CMDType.AGENTINFO : WSNListAgentsReply,
	CMDType.SDSRV : WSNServerSocketData,
	CMDType.WRAPSSL : WSNSocketWrapSSL,
}