import platform
import os
import asyncio
import socket
import struct
import ipaddress
import typing
import traceback
import shutil

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

class TCPServerConnection:
	def __init__(self, agent, token, ip, port):
		self.agent = agent
		self.token = token
		self.ip = ip
		self.port = port
	
	async def handle_server_client_write(self, connectiontoken, writer, disconnected_evt):
		try:
			while not disconnected_evt.is_set():
				data = await self.agent.server_queues[self.token][connectiontoken].get()
				print('out data: %s' % data)
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				writer.write(cmd.data)
				await writer.drain()
		except Exception as e:
			print(e)
			logger.exception('handle_server_client_write')
		finally:
			print('handle_server_client_write done!')
			disconnected_evt.set()
	
	async def handle_server_client(self, reader, writer):
		writer_task = None
		connectiontoken = self.agent.get_connection_id()
		disconnected_evt = asyncio.Event()
		try:
			self.agent.server_queues[self.token][connectiontoken] = asyncio.Queue()
			writer_task = asyncio.create_task(self.handle_server_client_write(connectiontoken, writer, disconnected_evt))
			while not disconnected_evt.is_set():
				data = await reader.read(65536)
				reply = WSNServerSocketData(self.token, connectiontoken, data)
				print(reply.to_bytes())
				await self.agent.send_data(reply.to_bytes())
				if data == b'':
					return

		except Exception as e:
			print(e)
			logger.exception('handle_server_client')
		finally:
			print('handle_server_client done!')
			disconnected_evt.set()
			if writer_task is not None:
				writer_task.cancel()
			del self.agent.server_queues[self.token][connectiontoken]

def address_resolver(ip_or_hostname:str):
	try:
		ipaddress.ip_address(ip_or_hostname)
		try:
			return socket.gethostbyaddr(ip_or_hostname)[0]
		except:
			return ''
	except:
		pass
	
	try:
		ip = socket.gethostbyname(ip_or_hostname)
		return ip
	except:
		return ''

async def resolve_single_addr(
    addr: str,
    executor,
    timeout: float = 0.2,
) -> typing.Optional[str]:
    """
    Resolves a single address, enforcing a timeout (in seconds).
    Returns the resolved result or None if there's a timeout/error.
    """
    loop = asyncio.get_event_loop()
    try:
        # run_in_executor returns an awaitable, which we wrap with wait_for
        return await asyncio.wait_for(
            loop.run_in_executor(executor, address_resolver, addr),
            timeout=timeout
        )
    except (asyncio.TimeoutError, Exception) as e:
        # Timeout or other exception
        print(f"Failed to resolve {addr}: {e}")
        return None

async def resolve_addresses(agent, executor, cmd):
	try:
		print('Resolving addresses')
		cmd = typing.cast(WSNResolv, cmd)
		res = []

		tasks = [
            asyncio.create_task(resolve_single_addr(addr, executor, timeout=0.2))
            for addr in cmd.ip_or_hostnames
        ]
			
		results = await asyncio.gather(*tasks, return_exceptions=True)

		for addr, result in zip(cmd.ip_or_hostnames, results):
			if isinstance(result, Exception) or result is None:
				res.append('')
			else:
				res.append(result)

		print('Resolved addresses: %s' % res)
		reply = WSNResolv(cmd.token, res)
		await agent.send_data(reply.to_bytes())
	except Exception as e:
		traceback.print_exc()
		await agent.send_err(cmd, 'Resolve failed', e)

class WSNETAgent:
	def __init__(self, transport:GenericTransport, send_full_exception:bool = True):
		self.transport = transport
		self.send_full_exception = send_full_exception

		self.connections = {} #connection_id -> smbmachine
		self.__conn_id = 10
		self.__process_queues = {} #token -> in_queue
		self.server_queues = {} #token -> {connectiontoken -> in_queue}
		self.file_queues = {}
		self.__servers = {} #token -> server
		self.__running_tasks = {} #token -> task
		self.executor = None
		try:
			from concurrent.futures import ThreadPoolExecutor
			self.executor = ThreadPoolExecutor(max_workers=50)
		except:
			pass

	def get_connection_id(self):
		t = self.__conn_id
		self.__conn_id += 1
		return str(t).ljust(16, 'L').encode()

	async def terminate(self):
		for token in self.__running_tasks:
			self.__running_tasks[token].cancel()
		self.__running_tasks = {}

		for token in self.__servers:
			self.__servers[token].cancel()
		self.__servers = {}

	
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
				data = await self.server_queues[token][connectiontoken].get()
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
				data = await self.server_queues[token][connectiontoken].get()
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				writer.write(cmd.data)
				await writer.drain()
		except Exception as e:
			logger.exception('handle_server_client_write')
		finally:
			print('handle_server_client_write done!')
			disconnected_evt.set()

	async def handle_server_client(self, token, reader, writer, disconnected_evt):
		writer_task = None
		try:
			connectiontoken = self.get_connection_id()
			self.server_queues[token][connectiontoken] = asyncio.Queue()
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
			print('handle_server_client done!')
			disconnected_evt.set()
			if writer_task is not None:
				writer_task.cancel()
			del self.server_queues[token][connectiontoken]
		

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
					print('UDP connect')
					print('Client connecting to %s:%s' % (cmd.ip, cmd.port))
					try:
						udp_connection_token = b'\x00'*16
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, remote_addr=(cmd.ip, int(cmd.port)))
						x = asyncio.create_task(self.handle_udp_writer(cmd.token, udp_connection_token, servertransport, disconnected_evt))
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token][udp_connection_token] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						while not disconnected_evt.is_set():
							x = await in_queue.get()
							data, addr = x
							reply = WSNServerSocketData(cmd.token, udp_connection_token, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()
					except Exception as e:
						print(e)
						traceback.print_exc()
			else:
				# bind command
				if cmd.protocol == 'TCP':
					if cmd.bindtype == 1:
						#normal bind
						connection = TCPServerConnection(self, cmd.token, cmd.ip, cmd.port)
						self.server_queues[cmd.token] = {}
						logger.debug('Client binding to %s:%s' % (cmd.ip, cmd.port))
						
						server = await asyncio.start_server(connection.handle_server_client, host=str(cmd.ip), port=int(cmd.port))
						await self.send_continue(cmd)
						self.__servers[cmd.token] = asyncio.create_task(server.serve_forever())
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
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
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
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
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
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
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
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token]['1'*16] = writer_queue #since it's udp there is only one 'stream'
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

	async def process_fileop(self, cmd:CMD):
		try:
			if cmd.type == CMDType.DIRRM:
				cmd = typing.cast(WSNDirRM, cmd)
				shutil.rmtree(cmd.path)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.DIRMK:
				cmd = typing.cast(WSNDirMK, cmd)
				os.makedirs(cmd.path)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.DIRCOPY:
				cmd = typing.cast(WSNDirCopy, cmd)
				shutil.copytree(cmd.srcpath, cmd.dstpath)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.DIRMOVE:
				cmd = typing.cast(WSNDirMove, cmd)
				shutil.move(cmd.srcpath, cmd.dstpath)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.DIRLS:
				for root, dirs, files in os.walk(cmd.path):
					if root != cmd.path:
						break
					for file in files:
						fullepath = os.path.join(root, file)
						try:
							stat = os.stat(fullepath)
							size = stat.st_size
							atime = stat.st_atime_ns
							mtime = stat.st_mtime_ns
							ctime = stat.st_ctime_ns
						except:
							size = 0
							atime = 0
							mtime = 0
							ctime = 0
						fe = WSNFileEntry(cmd.token, root, file, False, size, atime, mtime, ctime)
						await self.send_data(fe.to_bytes())
					for dir in dirs:
						fullepath = os.path.join(root, dir)
						try:
							stat = os.stat(fullepath)
							size = 0
							atime = stat.st_atime_ns
							mtime = stat.st_mtime_ns
							ctime = stat.st_ctime_ns
						except:
							size = 0
							atime = 0
							mtime = 0
							ctime = 0
						fe = WSNFileEntry(cmd.token, root, dir, True, size, atime, mtime, ctime)
						await self.send_data(fe.to_bytes())
				await self.send_ok(cmd)
			elif cmd.type == CMDType.FILECOPY:
				cmd = typing.cast(WSNFileCopy, cmd)
				shutil.copy(cmd.srcpath, cmd.dstpath)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.FILEMOVE:
				cmd = typing.cast(WSNFileMove, cmd)
				shutil.move(cmd.srcpath, cmd.dstpath)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.FILERM:
				cmd = typing.cast(WSNFileRM, cmd)
				os.remove(cmd.path)
				await self.send_ok(cmd)
			elif cmd.type == CMDType.FILEOPEN:
				cmd = typing.cast(WSNFileOpen, cmd)
				if cmd.mode == 'rb' or cmd.mode == 'r' or cmd.mode == 'wb' or cmd.mode == 'w':
					if 'r' in cmd.mode:
						f = open(cmd.path, 'rb')
					else:
						f = open(cmd.path, 'wb')
					self.file_queues[cmd.token] = f
					await self.send_continue(cmd)
				else:
					await self.send_err(cmd, 'Mode not supported', '')
			elif cmd.type == CMDType.FILEREAD:
				cmd = typing.cast(WSNFileRead, cmd)
				f = self.file_queues[cmd.token]
				f.seek(cmd.offset, 0)
				data = f.read(cmd.size)
				reply = WSNFileData(cmd.token, data, offset = f.tell() - len(data))
				await self.send_data(reply.to_bytes())
			elif cmd.type == CMDType.FILEDATA:
				cmd = typing.cast(WSNFileData, cmd)
				f = self.file_queues[cmd.token]
				f.seek(cmd.offset, 0)
				f.write(cmd.data)
				await self.send_continue(cmd)
			elif cmd.type == CMDType.FILESTAT:
				cmd = typing.cast(WSNFileStat, cmd)
				f = self.file_queues[cmd.token]
				stat = os.fstat(f.fileno())
				reply = WSNFileEntry(cmd.token, '','', False, stat.st_size, stat.st_atime_ns, stat.st_mtime_ns, stat.st_ctime_ns)
				await self.send_data(reply.to_bytes())
			else:
				await self.send_err(cmd, 'File operation %s not implemented' % cmd.type.value, '')
		except:
			traceback.print_exc()
			await self.send_err(cmd, 'File operation failed %s' % cmd.type, traceback.format_exc())

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
			
			if cmd.token in self.file_queues and cmd.type == CMDType.OK:
				f = self.file_queues[cmd.token]
				f.close()
				del self.file_queues[cmd.token]
				return True, None
					
			if cmd.type == CMDType.SDSRV:
				#print('Server data incoming! %s' % cmd)
				cmd = typing.cast(WSNServerSocketData, cmd)
				await self.server_queues[cmd.token][cmd.connectiontoken].put(cmd)

			elif cmd.type == CMDType.RESOLV:
				asyncio.create_task(resolve_addresses(self, self.executor, cmd))
					
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
							str(logon['usersid']),
							'%s' % platform.system().upper(),
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
							'',
							'%s' % platform.system().upper(),
						)
					await self.send_data(info.to_bytes())
					await self.send_ok(cmd)
				except Exception as e:
					await self.send_err(cmd, str(e), e)
			elif cmd.type.value >= 300 and cmd.type.value < 320:
				await self.process_fileop(cmd)
			return True, None
		except Exception as e:
			logger.exception('handle_incoming')
			return None, e
