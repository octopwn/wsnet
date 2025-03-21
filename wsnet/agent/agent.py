import platform
import os
import asyncio
import socket
import struct
import ipaddress
import typing
import traceback
import shutil
import netifaces

from wsnet import logger
from wsnet.protocol import *

class GenericTransport:
	def __init__(self):
		pass

	async def send(self, data:bytes):
		raise NotImplementedError()

def get_ips_from_interface(interface:str, ip_version:int = 4):
	ips = []
	if ip_version == 4:
		addresses = netifaces.ifaddresses(interface)
		if netifaces.AF_INET in addresses:
			for addr_info in addresses[netifaces.AF_INET]:
				ips.append(addr_info['addr'])
	elif ip_version == 6:
		addresses = netifaces.ifaddresses(interface)
		if netifaces.AF_INET6 in addresses:
			for addr_info in addresses[netifaces.AF_INET6]:
				ips.append(addr_info['addr'])
	return ips

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
	
	def error_received(self, exc):
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
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				writer.write(cmd.data)
				await writer.drain()
		except Exception as e:
			logger.exception('handle_server_client_write')
		finally:
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
				await self.agent.send_data(reply.to_bytes())
				if data == b'':
					return

		except Exception as e:
			logger.exception('handle_server_client')
		finally:
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
        return None

async def resolve_addresses(agent, executor, cmd):
	try:
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

		reply = WSNResolv(cmd.token, res)
		await agent.send_data(reply.to_bytes())
	except Exception as e:
		await agent.send_err(cmd, 'Resolve failed', e)

class UDPConnHandler:
	def __init__(self, agent, token, connectiontoken, transport, in_queue, writer_queue, disconnected_evt):
		self.agent = agent
		self.token = token
		self.connectiontoken = connectiontoken #b'1'*16
		self.transport = transport
		self.disconnected_evt = disconnected_evt
		self.writer_queue = writer_queue
		self.in_queue = in_queue
		self._running = True
		self._watchdog_task = None
		self._writer_task = None

	async def terminate(self):
		if self._running is False:
			return
		self._running = False

		self.disconnected_evt.set()
		self.transport.close()
		if self._watchdog_task is not None:
			self._watchdog_task.cancel()
		if self._writer_task is not None:
			self._writer_task.cancel()

	async def disconnect_watchdog(self):
		try:
			await self.disconnected_evt.wait()
			await self.terminate()
		except:
			pass

	async def run(self):
		try:
			self._watchdog_task = asyncio.create_task(self.disconnect_watchdog())
			self._writer_task = asyncio.create_task(self.handle_udp_writer())
			while True:
				x = await self.in_queue.get()
				data, addr = x
				if data is None:
					return
				reply = WSNServerSocketData(self.token, self.connectiontoken, data, addr[0], addr[1])
				await self.agent.send_data(reply.to_bytes())
		except Exception as e:
			logger.exception('handle_reader')
		finally:
			await self.terminate()
	
	async def handle_udp_writer(self):
		try:
			while True:				
				data = await self.writer_queue.get()
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				self.transport.sendto(cmd.data, (str(cmd.clientip), cmd.clientport))

		except Exception as e:
			logger.exception('handle_udp_writer')
		finally:
			await self.terminate()



class WSNETAgent:
	def __init__(self, transport:GenericTransport, send_full_exception:bool = True):
		self.transport = transport
		self.send_full_exception = send_full_exception

		self.__pid = ''
		self.__username = ''
		self.__domain = ''
		self.__logonserver = ''
		self.__logonserverip = ''
		self.__hostname = ''
		self.__cpuarch = ''
		self.__usersid = ''
		self.connections = {} #connection_id -> smbmachine
		self.__conn_id = 10
		self.__process_queues = {} #token -> in_queue
		self.server_queues = {} #token -> {connectiontoken -> in_queue}
		self.file_queues = {}
		self.__servers = {} #token -> server
		self.__running_tasks = {} #token -> task
		self.executor = None
		try:
			# this is used for name resolution
			from concurrent.futures import ThreadPoolExecutor
			self.executor = ThreadPoolExecutor(max_workers=50)
		except:
			pass

		self.get_basic_info()

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

	def get_basic_info(self):
		self.__pid = str(os.getpid())
		self.__username = str(os.getlogin())
		self.__domain = ''
		self.__logonserver = ''
		self.__logonserverip = ''
		self.__hostname = str(socket.getfqdn())
		self.__cpuarch = 'X64'
		self.__usersid = ''
		
		if platform.system() == 'Windows':
			from winacl.functions.highlevel import get_logon_info
			logon = get_logon_info()
			self.__username = str(logon['username'])
			self.__domain   = str(logon['domain'])
			self.__logonserver = str(logon['logonserver'])
			self.__usersid = str(logon['usersid'])
			self.__logonserverip = str(socket.getfqdn(logon['logonserver']))
	
	async def handle_info(self, cmd:WSNGetInfo):
		try:
			info = WSNGetInfoReply(
				cmd.token,
				self.__pid,
				self.__username,
				self.__domain,
				self.__logonserver,
				self.__cpuarch,
				self.__hostname, 
				self.__usersid,
				'%s' % platform.system().upper(),
				self.__logonserverip
			)
			await self.send_data(info.to_bytes())
			await self.send_ok(cmd)
		except Exception as e:
			await self.send_err(cmd, str(e), e)

	async def handle_udp_writer(self, token, connectiontoken, transport, disconnected_evt):
		try:
			while not disconnected_evt.is_set():
				data = await self.server_queues[token][connectiontoken].get()
				cmd = typing.cast(WSNServerSocketData, data)
				if cmd.data == b'':
					return
				#print('Sending %s to %s:%s' % (cmd.data, cmd.clientip, cmd.clientport))
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
					reader, writer = await asyncio.wait_for(asyncio.open_connection(cmd.ip, int(cmd.port)), timeout=5) #TODO: maybe should remotely set timeout?
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
							if isinstance(addr, Exception):
								continue
							reply = WSNServerSocketData(cmd.token, udp_connection_token, data, addr[0], addr[1])
							await self.send_data(reply.to_bytes())
						
						servertransport.close()
					except Exception as e:
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
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.bind((cmd.ip, cmd.port))
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						connectiontoken = b'1'*16
						handler = UDPConnHandler(self, cmd.token, connectiontoken, servertransport, in_queue, writer_queue, disconnected_evt)

						self.__servers[cmd.token] = asyncio.create_task(handler.run())
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token][connectiontoken] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						
					elif cmd.bindtype == 2:
						#LLMNR
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)

						sock.bind(('', 5355))
						llmnr_addr = "224.0.0.252"
						llmnr_addr6 = "FF02:0:0:0:0:0:1:3"

						# IPv4
						for ip in get_ips_from_interface(cmd.ip, 4):
							mreq = socket.inet_aton(llmnr_addr) + socket.inet_aton(ip)
							sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

						# IPv6
						try:
							if_index = socket.if_nametoindex(cmd.ip)
							mreq6 = socket.inet_pton(socket.AF_INET6, llmnr_addr6) + struct.pack('@I', if_index)
							sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq6)
						except Exception as e:
							pass
						
						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						connectiontoken = b'1'*16
						handler = UDPConnHandler(self, cmd.token, connectiontoken, servertransport, in_queue, writer_queue, disconnected_evt)

						self.__servers[cmd.token] = asyncio.create_task(handler.run())
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token][connectiontoken] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
						
					
					elif cmd.bindtype == 3:
						# NBTNS
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
						for ip in get_ips_from_interface(cmd.ip, 4):
							sock.bind((ip, 137))
							break
						
						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						connectiontoken = b'1'*16
						handler = UDPConnHandler(self, cmd.token, connectiontoken, servertransport, in_queue, writer_queue, disconnected_evt)

						self.__servers[cmd.token] = asyncio.create_task(handler.run())
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token][connectiontoken] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)
					
					elif cmd.bindtype == 4:
						# MDNS
						sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
						sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
						sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
						mdns_addr = "224.0.0.251"
						mdns_addr6 = "FF02::FB"
						sock.bind(('', 5353))

						# IPv4
						for ip in get_ips_from_interface(cmd.ip,  4):
							mreq = socket.inet_aton(mdns_addr) + socket.inet_aton(ip)
							sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

						# IPv6
						try:
							if_index = socket.if_nametoindex(cmd.ip)
							mreq6 = socket.inet_pton(socket.AF_INET6, mdns_addr6) + struct.pack('@I', if_index)
							sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq6)
						except Exception as e:
							pass

						sock.setblocking(False)
						in_queue = asyncio.Queue()
						writer_queue = asyncio.Queue()
						disconnected_evt = asyncio.Event()
						protofactory = lambda: UDPServerProtocol(in_queue, disconnected_evt)
						servertransport, serverproto = await asyncio.get_event_loop().create_datagram_endpoint(protofactory, sock=sock)
						connectiontoken = b'1'*16
						handler = UDPConnHandler(self, cmd.token, connectiontoken, servertransport, in_queue, writer_queue, disconnected_evt)

						self.__servers[cmd.token] = asyncio.create_task(handler.run())
						self.server_queues[cmd.token] = {}
						self.server_queues[cmd.token][connectiontoken] = writer_queue #since it's udp there is only one 'stream'
						await self.send_continue(cmd)



		except Exception as e:
			logger.debug("Socket handling error: %s\n%s", e, traceback.format_exc())
			await self.send_err(cmd, 'Socket connect failed: %s' % e, e)
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
			await self.send_err(cmd, 'File operation failed %s' % cmd.type, traceback.format_exc())

	async def process_incoming(self, data_raw:bytes):
		try:
			try:
				cmd = CMD.from_bytes(data_raw)
			except Exception as e:
				logger.exception('CMD raw parsing failed! %s' % repr(data_raw))
				return True, None
			
			#print('Incoming command: %s' % cmd)

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
				if cmd.token in self.server_queues:
					if cmd.connectiontoken in self.server_queues[cmd.token]:
						await self.server_queues[cmd.token][cmd.connectiontoken].put(cmd)
					else:
						await self.send_err(cmd, 'Server connection token not found', '')
				else:
					await self.send_err(cmd, 'Server token not found', '')

			elif cmd.type == CMDType.RESOLV:
				asyncio.create_task(resolve_addresses(self, self.executor, cmd))
					
			if cmd.type == CMDType.CONNECT: 
				self.__running_tasks[cmd.token] = asyncio.create_task(self.socket_connect(cmd))
			elif cmd.type == CMDType.SD:
				await self.send_err(cmd, 'Unexpected token for socket data!', '')
			elif cmd.type == CMDType.GETINFO:
				await self.handle_info(cmd)
			elif cmd.type.value >= 300 and cmd.type.value < 320:
				await self.process_fileop(cmd)
			return True, None
		except Exception as e:
			logger.exception('handle_incoming')
			return None, e
