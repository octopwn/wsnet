import websockets
import asyncio
import uuid
import enum
import datetime
import base64
import os
import traceback

from wsnet import logger
from wsnet.protocol import *

class dummyEnum(enum.Enum):
	UNKNOWN = 'UNKNOWN'

class WSNETAgent:
	def __init__(self, ws, session_id = None, db_session = None):
		self.ws = ws
		self.db_session = db_session
		self.incoming_task = None
		self.send_full_exception = False
		self.file_chunk_size = 4096
		self.session_id = session_id if session_id is not None else str(uuid.uuid4())

		self.connections = {} #connection_id -> smbmachine
		#self.shares = {} #connection_id -> {sharename} -> SMBShare
		self.__conn_id = 0
		self.__process_queues = {} #token -> in_queue
		self.__running_tasks = {} #token -> task

	def __get_connection_id(self):
		t = self.__conn_id
		self.__conn_id += 1
		return str(t)

	async def log_actions(self, cmd, state, msg):
		cmd = cmd.__dict__
		path = cmd.get('path')

		logd = {
			'timestamp' : datetime.datetime.utcnow().isoformat(),
			'sessionid' : self.session_id,
			'connectionid' : cmd.get('cid'),
			'token' : cmd.get('token', b'').hex(),
			'cmdtype' : cmd.get('type', dummyEnum.UNKNOWN).value,
			'state' : state,
			'path' : path,
			'msg' : msg,
		}

		logline = '[%s][%s][%s][%s][%s][%s][%s] %s' % (
			logd['timestamp'], 
			logd['sessionid'], 
			logd['connectionid'], 
			logd['token'], 
			logd['cmdtype'], 
			logd['state'], 
			logd['path'],
			logd['msg'],
		)
		logger.debug(logline)
	
	async def log_start(self, cmd, msg = ''):
		await self.log_actions(cmd, 'START', msg)
	
	async def log_ok(self, cmd, msg = ''):
		await self.log_actions(cmd, 'DONE', msg)

	async def log_err(self, cmd, exc):
		await self.log_actions(cmd, 'ERR', str(exc)) #TODO: better exception formatting?

	async def terminate(self):
		#not a command, only called when the connection is lost so the smb clients can be shut down safely
		pass
	

	async def send_ok(self, cmd):
		try:
			reply = WSNOK(cmd.token)
			await self.log_ok(cmd)
			await self.ws.send(reply.to_bytes())
			
		except Exception as e:
			print(e)

	async def send_continue(self, cmd):
		try:
			reply = WSNContinue(cmd.token)
			await self.ws.send(reply.to_bytes())
		except Exception as e:
			print(e)

	async def send_err(self, cmd, reason, exc):
		try:
			extra = ''
			if self.send_full_exception is True:
				extra = str(exc)
			reply = WSNErr(cmd.token, reason, extra)
			await self.log_err(cmd, exc)
			await self.ws.send(reply.to_bytes())
		except Exception as e:
			print(e)

	async def socket_connect(self, cmd):
		out_task = None
		try:
			await self.log_start(cmd)
			if cmd.protocol == 'TCP':
				logger.debug('Client connecting to %s:%s' % (cmd.ip, cmd.port))
				reader, writer = await asyncio.open_connection(cmd.ip, int(cmd.port))
				logger.debug('Connection to %s:%s established' % (cmd.ip, cmd.port))
				in_q = asyncio.Queue()
				self.__process_queues[cmd.token] = in_q
				out_task = asyncio.create_task(self.__socket_data_in_handle(cmd.token, in_q, reader, writer))
				await self.send_continue(cmd)
				while True:
					await asyncio.sleep(0)
					data = await reader.read(65536) #helps smb a lot
					if data == b'':
						await self.send_ok(cmd)
						return

					reply = WSNSocketData(cmd.token, data)
					await self.ws.send(reply.to_bytes())

				return
			else:
				raise NotImplementedError()

		except Exception as e:
			logger.exception('socket_connect')
			await self.send_err(cmd, 'Socket connect failed', e)
		finally:
			if out_task is not None:
				out_task.cancel()

	async def __socket_data_in_handle(self, token, in_q, reader, writer):
		try:
			while True:
				cmd = await in_q.get()
				if cmd.type == CMDType.OK:
					#we are cone here!
					print('GOT OK! Cancelling socket!!')
					#await self.send_ok(cmd)
					return
				elif cmd.type == CMDType.SD:
					await asyncio.sleep(0)
					writer.write(cmd.data)
					await writer.drain()

		except Exception as e:
			logger.exception('__socket_data_in_handle')
			await self.send_err(cmd, 'socket_in failed', e)
		finally:
			writer.close()
			del self.__process_queues[token]



	async def handle_incoming(self):
		try:
			while True:
				try:
					data_raw = await self.ws.recv()
					#logger.debug('data_raw %s' % repr(data_raw))
					
					try:
						cmd = CMD.from_bytes(data_raw)
					except Exception as e:
						logger.exception('CMD raw parsing failed! %s' % repr(data_raw))
						continue

					if cmd.token in self.__process_queues:
						await self.__process_queues[cmd.token].put(cmd)
						continue
					
					if cmd.type == CMDType.CONNECT: 
						self.__running_tasks[cmd.token] = asyncio.create_task(self.socket_connect(cmd))
					elif cmd.type == CMDType.SD:
						await self.send_err(cmd, 'Unexpected token for socket data!', '')
						
				except Exception as e:
					logger.exception('handle_incoming')
					return
		finally:
			pass
			#await self.__disconnect_all()

	async def run(self):
		self.incoming_task = asyncio.create_task(self.handle_incoming())
		await self.incoming_task