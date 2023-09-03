import platform
import os
import asyncio
import socket
import struct
import ipaddress
import typing
import traceback

from wsnet import logger
from wsnet.protocol import *

class GenericTransport:
	def __init__(self):
		pass

	async def send(self, data:bytes):
		raise NotImplementedError()

# https://gist.github.com/vxgmichel/e47bff34b68adb3cf6bd4845c4bed448
class UDPServerProtocol:
	def __init__(self, in_queue:asyncio.Queue, disconnected_evt:asyncio.Event):
		self.in_queue = in_queue
		self.disconnected_evt = disconnected_evt

	def connection_made(self, transport):
		self.transport = transport

	def datagram_received(self, data, addr):
		#message = data.decode()
		#print('Received %r from %s' % (message, addr))
		#print('Send %r to %s' % (message, addr))
		#self.transport.sendto(data, addr)
		self.in_queue.put_nowait((data, addr))
	
	def connection_lost(self, exc):
		self.in_queue.put_nowait((None, exc))

class WSNETAgent:
	def __init__(self, transport:GenericTransport, send_full_exception:bool = True):
		self.transport = transport
		self.send_full_exception = send_full_exception

		self.connections = {} #connection_id -> smbmachine
		self.__conn_id = 0
		self.__process_queues = {} #token -> in_queue
		self.__server_queues = {} #token -> {connectiontoken -> in_queue}
		self.__running_tasks = {} #token -> task

	def __get_connection_id(self):
		t = self.__conn_id
		self.__conn_id += 1
		return str(t)

	async def terminate(self):
		#not a command, only called when the connection is lost so the smb clients can be shut down safely
		pass
	
	async def send_data(self, data:bytes):
		await self.transport.send(data)

	async def send_ok(self, cmd):
		reply = WSNOK(cmd.token)
		await self.send_data(reply.to_bytes())

	async def send_continue(self, cmd):
		reply = WSNContinue(cmd.token)
		await self.send_data(reply.to_bytes())

	async def send_err(self, cmd, reason, exc):
		extra = ''
		if self.send_full_exception is True:
			extra = str(exc)
		reply = WSNErr(cmd.token, reason, extra)
		await self.send_data(reply.to_bytes())

	async def handle_udp_writer(self, token, connectiontoken, transport, disconnected_evt):
		try:
			while not disconnected_evt.is_set():
				data = await self.__server_queues[token][connectiontoken].get()
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				transport.sendto(cmd.data, (str(cmd.clientip), cmd.clientport))

		except Exception as e:
			logger.exception('handle_udp_writer')
		finally:
			disconnected_evt.set()

	async def handle_server_client_write(self, token, connectiontoken, writer, disconnected_evt):
		try:
			while not disconnected_evt.is_set():
				data = await self.__server_queues[token][connectiontoken].get()
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				writer.write(cmd.data)
				await writer.drain()
		except Exception as e:
			logger.exception('handle_server_client_write')
		finally:
			disconnected_evt.set()

	async def handle_server_client(self, token, reader, writer, disconnected_evt):
		writer_task = None
		try:
			connectiontoken = self.__get_connection_id()
			self.__server_queues[token][connectiontoken] = asyncio.Queue()
			writer_task = await asyncio.create_task(self.handle_server_client_write(token, connectiontoken, writer, disconnected_evt))
			while not disconnected_evt.is_set():
				data = await reader.read(65536)
				reply = WSNServerSocketData(token, connectiontoken, data)
				await self.send_data(reply.to_bytes())
				if data == b'':
					return

		except Exception as e:
			logger.exception('handle_server_client')
		finally:
			disconnected_evt.set()
			if writer_task is not None:
				writer_task.cancel()
			del self.__server_queues[token][connectiontoken]
		

	async def socket_connect(self, cmd:WSNConnect):
		out_task = None
		try:
			if cmd.bind is False:
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
						await self.send_data(reply.to_bytes())

					return
				else:
					# not tested!!!!
					in_queue = asyncio.Queue()
					writer_queue = asyncio.Queue()
					disconnected_evt = asyncio.Event()
					protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
					servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory)
					x = asyncio.create_task(self.handle_udp_writer(cmd.token, '1'*16, writer_queue, disconnected_evt))
					self.__server_queues[cmd.token] = {}
					self.__server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
					await self.send_continue(cmd)
					while not disconnected_evt.is_set():
						x = await in_queue.get()
						data, addr = x
						reply = WSNServerSocketData(cmd.token, '1'*16, data, addr[0], addr[1])
						await self.send_data(reply.to_bytes())
					
					servertransport.close()
			else:
				# bind command
				if cmd.protocol == 'TCP':
					if cmd.bindtype == 1:
						#normal bind
						self.__server_queues[cmd.token] = {}
						logger.debug('Client binding to %s:%s' % (cmd.ip, cmd.port))
						disconnected_evt = asyncio.Event()
						server = await asyncio.start_server(lambda r, w: self.handle_server_client(cmd.token, r, w, disconnected_evt), cmd.ip, int(cmd.port))
						async with server:
							await self.send_continue(cmd)
							await server.serve_forever()
					else:
						await self.send_err(cmd, 'Selected bindtype not implemented for TCP')
				else:
					#udp server
					if cmd.bindtype == 1:
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory)
						x = asyncio.create_task(self.handle_udp_writer(cmd.token, '1'*16, writer_queue, disconnected_evt))
						self.__server_queues[cmd.token] = {}
						self.__server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						while not disconnected_evt.is_set():
							x = await in_queue.get()
							data, addr = x
							reply = WSNServerSocketData(cmd.token, '1'*16, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()
						
					elif cmd.bindtype == 2:
						#LLMNR
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.bind(('', 5355))
						group = ipaddress.ip_address('224.0.0.252').packed
						mreq = struct.pack('4sL', group, socket.INADDR_ANY)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						x = asyncio.create_task(self.handle_udp_writer(cmd.token, '1'*16, writer_queue, disconnected_evt))
						self.__server_queues[cmd.token] = {}
						self.__server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						while not disconnected_evt.is_set():
							x = await in_queue.get()
							data, addr = x
							reply = WSNServerSocketData(cmd.token, '1'*16, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()
					
					elif cmd.bindtype == 3:
						# NBTNS
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.bind((cmd.ip, cmd.port))
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						x = asyncio.create_task(self.handle_udp_writer(cmd.token, '1'*16, writer_queue, disconnected_evt))
						self.__server_queues[cmd.token] = {}
						self.__server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						while not disconnected_evt.is_set():
							x = await in_queue.get()
							data, addr = x
							reply = WSNServerSocketData(cmd.token, '1'*16, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()
					
					elif cmd.bindtype == 4:
						# MDNS
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.bind(('0.0.0.0', 5353))
						group = ipaddress.ip_address('224.0.0.251').packed
						mreq = struct.pack('4sL', group, socket.INADDR_ANY)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						x = asyncio.create_task(self.handle_udp_writer(cmd.token, '1'*16, writer_queue, disconnected_evt))
						self.__server_queues[cmd.token] = {}
						self.__server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						while not disconnected_evt.is_set():
							x = await in_queue.get()
							data, addr = x
							reply = WSNServerSocketData(cmd.token, '1'*16, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()



		except Exception as e:
			logger.debug("Socket handling error: %s\n%s", e, traceback.format_exc())
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
					#print('GOT OK! Cancelling socket!!')
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

	async def process_incoming(self, data_raw:bytes):
		try:
			try:
				cmd = CMD.from_bytes(data_raw)
			except Exception as e:
				logger.exception('CMD raw parsing failed! %s' % repr(data_raw))
				return True, None
					
			if cmd.token in self.__process_queues:
				await self.__process_queues[cmd.token].put(cmd)
				return True, None
					
			if cmd.type == CMDType.SDSRV:
				cmd = typing.cast(WSNServerSocketData, cmd)
				if cmd.token in self.__server_queues:
					if cmd.connectiontoken in self.__server_queues:
						await self.__server_queues[cmd.connectiontoken].put(cmd)
					
			if cmd.type == CMDType.CONNECT: 
				self.__running_tasks[cmd.token] = asyncio.create_task(self.socket_connect(cmd))
			elif cmd.type == CMDType.SD:
				await self.send_err(cmd, 'Unexpected token for socket data!', '')
			elif cmd.type == CMDType.GETINFO:
				try:
					if platform.system() == 'Windows':
						from winacl.functions.highlevel import get_logon_info
						logon = get_logon_info()
						info = WSNGetInfoReply(
							cmd.token, 
							str(os.getpid()), 
							str(logon['username']),
							str(logon['domain']),
							str(logon['logonserver']), 
							'X64', # TODO 
							str(socket.getfqdn()), 
							str(logon['usersid'])
						)
					else:
						info = WSNGetInfoReply(
							cmd.token, 
							str(os.getpid()), 
							str(os.getlogin()),
							'',
							'', 
							'X64', # TODO 
							str(socket.getfqdn()), 
							''
						)
					await self.send_data(info.to_bytes())
					await self.send_ok(cmd)
				except Exception as e:
					await self.send_err(cmd, str(e), e)
			return True, None
		except Exception as e:
			logger.exception('handle_incoming')
			return None, e
