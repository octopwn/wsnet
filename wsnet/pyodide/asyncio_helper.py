
import asyncio
import os
import io
import ssl


import traceback
from wsnet.protocol import *
from asyncio import events
from asyncio.streams import StreamReader, StreamWriter, StreamReaderProtocol
from asyncio.transports import Transport

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	print('Failed to import pyodide, using dummy test objects!')
	print('This is expected when running the test suite outside of pyodide!')
	from wsnet.pyodide.test_js import js as jsobj, to_js, create_proxy
	js = jsobj()

def patch_asyncio():
	asyncio.open_connection = open_connection
	loop = events.get_running_loop()
	loop.create_connection = create_connection

async def test_streamreader():
	try:
		reader, writer = await asyncio.open_connection('google.com', 80)
		writer.write(b'GET / HTTP/1.1\r\nHost: google.com\r\n\r\n\r\n')
		await writer.drain()
		data = await reader.read(1024)
		print('Received: {}'.format(data))
	except Exception as e:
		print('Exception: {}'.format(e))
		traceback.print_exc()

async def test_streamreader_ssl(host='google.com', port=443, ssl=True):
	try:
		reader, writer = await asyncio.open_connection(host, port, ssl=ssl)
		writer.write(b'GET / HTTP/1.1\r\nHost: %s\r\n\r\n\r\n' % host.encode('utf-8'))
		await writer.drain()
		data = await reader.read(1024)
		print('Received: {}'.format(data))
	except Exception as e:
		print('Exception: {}'.format(e))
		traceback.print_exc()



async def create_connection(protocol_factory, host=None, port=None,
			*, ssl=None, family=0,
			proto=0, flags=0, sock=None,
			local_addr=None, server_hostname=None,
			ssl_handshake_timeout=None,
			happy_eyeballs_delay=None, interleave=None):
	
	if sock is not None:
		raise NotImplementedError('Socket is not supported')
	if flags != 0:
		print('WSNET create_connection: The callee is passing flags to the socket. This is not supported. Flags: {}'.format(flags))
	if proto != 0:
		print('WSNET create_connection: The callee is passing proto to the socket. This is not supported. Proto: {}'.format(proto))
	if family != 0:
		print('WSNET create_connection: The callee is passing family to the socket. This is not supported. Family: {}'.format(family))
	if local_addr is not None:
		print('WSNET create_connection: The callee is passing local_addr to the socket. This is not supported. Local_addr: {}'.format(local_addr))
	if happy_eyeballs_delay is not None:
		print('WSNET create_connection: The callee is passing happy_eyeballs_delay to the socket. This is not supported. Happy_eyeballs_delay: {}'.format(happy_eyeballs_delay))
	if interleave is not None:
		print('WSNET create_connection: The callee is passing interleave to the socket. This is not supported. Interleave: {}'.format(interleave))
	
	wsnetcomm = WSNETConnection(host, port, ssl, server_hostname, ssl_handshake_timeout)
	result, err = await wsnetcomm.connect()
	if err is not None:
		raise err
	wsnettransport = WSNETTransport(wsnetcomm)
	protocol = protocol_factory()
	protocol.connection_made(wsnettransport)
	wsnettransport.set_protocol(protocol)
	return wsnettransport, protocol


async def open_connection(host, port, ssl=None, loop=None, limit=2 ** 16 , **kwds):
	loop = events.get_running_loop()
	reader = StreamReader(limit=limit, loop=loop)
	protocol = StreamReaderProtocol(reader, loop=loop)
	transport, _ = await create_connection(
		lambda: protocol, host, port, **kwds, ssl=ssl)
	writer = StreamWriter(transport, protocol, reader, loop)
	return reader, writer



class WSNETConnection:
	def __init__(self, host:str, port:int, ssl_ctx = None, server_hostname:str = None, ssl_handshake_timeout:int = None):
		self.ws_url:str = None
		self.ws_id:int = None
		self.ws_proxy = None
		self.connected_evt = asyncio.Event()
		self.disconnected_evt = asyncio.Event()
		self.internal_in_q = asyncio.Queue()
	
		self.host:str = host
		self.port:int = port
		self.ssl_ctx:ssl.SSLContext = ssl_ctx
		self.server_hostname:str = server_hostname
		self.ssl_handshake_timeout:int = ssl_handshake_timeout
		self.tls_in_buff = None
		self.tls_out_buff = None
		self.tls_obj = None

		self.in_q:asyncio.Queue = asyncio.Queue()
		self.out_q:asyncio.Queue = asyncio.Queue()
		self.reuse_ws:bool = True
		self.token:bytes = os.urandom(16)
	
		
		self.read_lock:asyncio.Lock = asyncio.Lock()
		self.read_pause:asyncio.Task = None
		self.conn_out_task:asyncio.Task = None
		self.conn_in_task:asyncio.Task = None
		self.protocol:asyncio.Protocol = None
	
	async def close(self):
		if self.protocol is not None:
			self.protocol.connection_lost(None)
		
		self.disconnected_evt.set()
		if self.conn_out_task is not None:
			self.conn_out_task.cancel()
		if self.conn_in_task is not None:
			self.conn_in_task.cancel()
		

		
	async def pause_reading(self):
		while True:
			async with self.read_lock:
				await asyncio.sleep(100)

	def get_extra_info(self, name, default=None):
		if name == 'sslcontext':
			return self.ssl_ctx
		else:
			return default
	
	async def connection_handler_in(self):
		try:
			print('WSNETConnection: connection_handler_in started')
			while not self.disconnected_evt.is_set():
				async with self.read_lock:
					print('WSNETConnection: connection_handler_in waiting for data')
					data_memview = await self.internal_in_q.get()
					print('got memview')
					cmd = CMD.from_bytes(data_memview.to_py())
					print('WSNETConnection: connection_handler_in got data: %s' % cmd.type)
					if cmd.type == CMDType.OK:
						#print('Remote end terminated the socket')
						raise Exception('Remote end terminated the socket')
					elif cmd.type == CMDType.ERR:
						#print('Proxy sent error during data transmission. Killing the tunnel.')
						raise Exception('Proxy sent error during data transmission. Killing the tunnel.')
					#await self.in_q.put((cmd.data, None))
					print('DATA IN: %s'	% cmd.data)
					self.protocol.data_received(cmd.data)
			print('WSNETConnection: connection_handler_in stopped')
		except Exception as e:
			traceback.print_exc()
			return			
		finally:
			await self.close()

	async def connection_handler_out(self):
		print('WSNETConnection: connection_handler_out started')
		try:
			while not self.disconnected_evt.is_set():
				data = await self.out_q.get()
				print('Write_in: %s' % data)
				if data is None or data == b'':
					return

				if len(data) < 286295:
					cmd = WSNSocketData(self.token, data)
					js.sendWebSocketData(self.ws_id, cmd.to_bytes())
				else:
					# need to chunk the data because WS only accepts max 286295 bytes in one message
					data = io.BytesIO(data)
					while not self.disconnected_evt.is_set():
						chunk = data.read(286200)
						if chunk == b'':
							break
						cmd = WSNSocketData(self.token, chunk)
						js.sendWebSocketData(self.ws_id, cmd.to_bytes())

		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				js.sendWebSocketData(self.ws_id, cmd.to_bytes())
			except:
				pass
			await self.close()
	
	########################## SSL ##########################
	async def __ssl_recv_one(self, remaining:bytearray):
		# used to recieve exactly one TLS record
		buffer = remaining
		if len(buffer) > 5:
			record_len = int.from_bytes(buffer[3:5], byteorder='big')
			print('record_len+5: %s' % (record_len+5))
			if len(buffer) >= record_len+5:
				print('returning buffer')
				return buffer[:record_len+5], buffer[record_len+5:]
		try:
			print('__ssl_recv_one with remaining: %s' % remaining)
			
			while not self.disconnected_evt.is_set():
				data = await self.internal_in_q.get()
				cmd = CMD.from_bytes(data.to_py())
				if cmd.type == CMDType.OK:
					#print('Remote end terminated the socket')
					raise Exception('Remote end terminated the socket')
				elif cmd.type == CMDType.ERR:
					#print('Proxy sent error during data transmission. Killing the tunnel.')
					raise Exception('Proxy sent error during data transmission. Killing the tunnel.')
				buffer += cmd.data
				if len(buffer) > 5:
					final_buffer = b''
					record_len = int.from_bytes(buffer[3:5], byteorder='big')
					print('record_len+5: %s' % (record_len+5))
					if len(buffer) >= record_len + 5:
						print('returning buffer and rest %s, %s' % (buffer[:record_len+5], buffer[record_len+5:]))
						final_buffer += buffer[:record_len+5]
					return final_buffer, buffer[len(final_buffer):]
						
		except Exception as e:
			traceback.print_exc()
			return b'', b''
		
	async def do_handshake(self):
		try:
			print('handshake')
			self.tls_in_buff = ssl.MemoryBIO()
			self.tls_out_buff = ssl.MemoryBIO()
			self.tls_obj = self.ssl_ctx.wrap_bio(self.tls_in_buff, self.tls_out_buff, server_side=False) # , server_hostname = self.monitor.dst_hostname

			ctr = 0
			rest = b''
			while not self.disconnected_evt.is_set():
				ctr += 1
				try:
					self.tls_obj.do_handshake()
				except ssl.SSLWantReadError:
					print('DST want %s' % ctr)
					if rest != b'':
						print('DST rest %s' % len(rest))
						server_hello, rest = await self.__ssl_recv_one(rest)
						print('DST server_hello 2 %s' % len(server_hello))
						if server_hello != b'':
							self.tls_in_buff.write(server_hello)
							continue

					while not self.disconnected_evt.is_set():
						client_hello = self.tls_out_buff.read()
						if client_hello != b'':
							print('DST client_hello %s' % len(client_hello))
							cmd = WSNSocketData(self.token, client_hello)
							js.sendWebSocketData(self.ws_id, cmd.to_bytes())
						else:
							break
					
					## ughh this is ugly
					server_hello, rest = await self.__ssl_recv_one(rest)
					if server_hello == b'':
						raise Exception('Server hello is empty')
					print('DST server_hello %s' % len(server_hello))
					print('DST server_hello %s' % server_hello)
					self.tls_in_buff.write(server_hello)

					continue
				except:
					raise
				else:
					print('DST handshake ok %s' % ctr)
					server_fin = self.tls_out_buff.read()
					print('DST server_fin %s ' %  server_fin)
					if server_fin != b'':
						cmd = WSNSocketData(self.token, server_fin)
						js.sendWebSocketData(self.ws_id, cmd.to_bytes())
					break
			return rest
		except Exception as e:
			traceback.print_exc()
			await self.close()
			return b''
	
	async def connection_handler_in_ssl(self, remaining:bytearray):
		try:
			buffer = remaining
			print('WSNETConnection: SSL connection_handler_in started')
			while not self.disconnected_evt.is_set():
				async with self.read_lock:
					print('WSNETConnection: SSL connection_handler_in waiting for data')
					data_memview = await self.internal_in_q.get()
					print('got memview')
					cmd = CMD.from_bytes(data_memview.to_py())
					print('WSNETConnection: SSL connection_handler_in got data: %s' % cmd.type)
					if cmd.type == CMDType.OK:
						#print('Remote end terminated the socket')
						raise Exception('SSL Remote end terminated the socket')
					elif cmd.type == CMDType.ERR:
						#print('Proxy sent error during data transmission. Killing the tunnel.')
						raise Exception('SSL Proxy sent error during data transmission. Killing the tunnel.')
					#await self.in_q.put((cmd.data, None))
					print('SSL DATA IN: %s'	% cmd.data)
					buffer += cmd.data
					if len(buffer) < 5:
						continue
					
					while len(buffer) > 5:
						record_len = int.from_bytes(buffer[3:5], byteorder='big')
						if len(buffer) >= record_len + 5:
							self.tls_in_buff.write(buffer[:record_len+5])
							buffer = buffer[record_len+5:]
						
					while not self.disconnected_evt.is_set():
						try:
							decdata = self.tls_obj.read()
						except ssl.SSLWantReadError:
							break
						self.protocol.data_received(decdata)
			print('WSNETConnection: connection_handler_in stopped')
		except Exception as e:
			traceback.print_exc()
			return			
		finally:
			await self.close()


	async def connection_handler_out_ssl(self):
		try:
			while not self.disconnected_evt.is_set():
				data = await self.out_q.get()
				print('SSL Write_in: %s' % data)
				if data is None or data == b'':
					return
				
				self.tls_obj.write(data)
				while not self.disconnected_evt.is_set():
					raw = self.tls_out_buff.read()
					if raw != b'':
						cmd = WSNSocketData(self.token, raw)
						js.sendWebSocketData(self.ws_id, cmd.to_bytes())
						continue
					break

		except Exception as e:
			traceback.print_exc()
			return
		finally:
			try:
				cmd = WSNOK(self.token)
				js.sendWebSocketData(self.ws_id, cmd.to_bytes())
			except:
				pass
			await self.close()


	async def connect(self):
		try:
			# setting up the JS-PY proxies that will be used for communicating with the JS side
			connected_evt_proxy = create_proxy(self.connected_evt)
			disconnected_evt_proxy = create_proxy(self.disconnected_evt)
			data_in_proxy = create_proxy(self.internal_in_q)

			# getting the WS URL from the JS side, and tasking javascript to create the WS connection
			self.ws_url = js.document.getElementById('proxyurl')
			self.ws_id = js.createNewWebSocket(str(self.ws_url.value), connected_evt_proxy, data_in_proxy, disconnected_evt_proxy, self.reuse_ws, to_js(self.token))

			# waiting for the WS to connect
			await asyncio.wait_for(self.connected_evt.wait(), 10)

			# sending the proxy connection request to the destination IP and port
			cmd = WSNConnect(self.token, 'TCP', self.host, self.port)
			js.sendWebSocketData(self.ws_id, cmd.to_bytes())

			# reading the first incoming data from the WS, which should be the proxy connection response
			data_memview = await self.internal_in_q.get()
			cmd = CMD.from_bytes(data_memview.to_py())
			if cmd.type != CMDType.CONTINUE:
				if cmd.type == CMDType.ERR:
					raise Exception('Connection failed, proxy sent error. Err: %s' % cmd.reason)
				raise Exception('Connection failed, expected CONTINUE, got %s' % cmd.type.value)

			# at this point the proxy has successfully connected to the destination IP and port
			if self.ssl_ctx is not None:
				print('WSNETConnection: SSL')
				if self.ssl_ctx is True:
					print('WSNETConnection: creating new SSL context')
					self.ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
					self.ssl_ctx.check_hostname = False
					self.ssl_ctx.verify_mode = ssl.CERT_NONE
					#cipher_suites = 'ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA'
					#self.ssl_ctx.set_ciphers(cipher_suites)
					#self.ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1  # Set the minimum supported TLS version to 1.0
					#self.ssl_ctx.maximum_version = ssl.TLSVersion.TLSv1_2  # Set the maximum supported TLS version to 1.2

				print('WSNETConnection: about to do handshake')
				
				rest = await self.do_handshake()
				self.conn_in_task = asyncio.create_task(self.connection_handler_in_ssl(rest))
				self.conn_out_task = asyncio.create_task(self.connection_handler_out_ssl())
			else:
				#  and we can start reading and writing data
				self.conn_in_task = asyncio.create_task(self.connection_handler_in())
				self.conn_out_task = asyncio.create_task(self.connection_handler_out())
			
			return True, None
		except Exception as e:
			traceback.print_exc()
			return False, e
	

class WSNETTransport(Transport):
	"""Base class for WSNET transport."""

	def __init__(self, comms:WSNETConnection, extra=None):
		Transport.__init__(self)
		self.write_buffer_size = 65535
		self.read_buffer_size = 65535
		self.comms = comms
		self._protocol = None
		self._isclosing = False

	def get_extra_info(self, name, default=None):
		"""Get optional transport information."""
		print('Extrainfo', name, default)
		return self.comms.get_extra_info(name, default)
		

	def is_closing(self):
		"""Return True if the transport is closing or closed."""
		print('is_closing')
		return self._isclosing

	def close(self):
		"""Close the transport.
		Buffered data will be flushed asynchronously.  No more data
		will be received.  After all buffered data is flushed, the
		protocol's connection_lost() method will (eventually) be
		called with None as its argument.
		"""
		print('close')
		x = asyncio.create_task(self.comms.close())

	def set_protocol(self, protocol):
		"""Set a new protocol."""
		print('set_protocol', protocol)
		self.comms.protocol = protocol

	def get_protocol(self):
		"""Return the current protocol."""
		return self.comms.protocol

	def is_reading(self):
		print('is_reading')
		"""Return True if the transport is receiving."""
		return self.comms.read_pause is not None

	def pause_reading(self):
		"""Pause the receiving end.
		No data will be passed to the protocol's data_received()
		method until resume_reading() is called.
		"""
		print('pause_reading')
		self.comms.read_pause = asyncio.create_task(self.comms.pause_reading())

	def resume_reading(self):
		"""Resume the receiving end.
		Data received will once again be passed to the protocol's
		data_received() method.
		"""
		print('resume_reading')
		self.comms.read_pause.cancel()
		self.comms.read_pause = None
	
	def set_write_buffer_limits(self, high=None, low=None):
		"""Set the high- and low-water limits for write flow control.
		These two values control when to call the protocol's
		pause_writing() and resume_writing() methods.  If specified,
		the low-water limit must be less than or equal to the
		high-water limit.  Neither value can be negative.
		The defaults are implementation-specific.  If only the
		high-water limit is given, the low-water limit defaults to an
		implementation-specific value less than or equal to the
		high-water limit.  Setting high to zero forces low to zero as
		well, and causes pause_writing() to be called whenever the
		buffer becomes non-empty.  Setting low to zero causes
		resume_writing() to be called only once the buffer is empty.
		Use of zero for either limit is generally sub-optimal as it
		reduces opportunities for doing I/O and computation
		concurrently.
		"""
		print('set_write_buffer_limits')
		raise NotImplementedError

	def get_write_buffer_size(self):
		print('get_write_buffer_size')
		"""Return the current size of the write buffer."""
		return self.write_buffer_size

	def get_write_buffer_limits(self):
		print('get_write_buffer_limits')
		"""Get the high and low watermarks for write flow control.
		Return a tuple (low, high) where low and high are
		positive number of bytes."""
		raise NotImplementedError

	def write(self, data):
		print('write', data)
		"""Write some data bytes to the transport.
		This does not block; it buffers the data and arranges for it
		to be sent out asynchronously.
		"""
		self.comms.out_q.put_nowait(data)

	def writelines(self, list_of_data):
		print('writelines', list_of_data)
		"""Write a list (or any iterable) of data bytes to the transport.
		The default implementation concatenates the arguments and
		calls write() on the result.
		"""
		data = b''.join(list_of_data)
		self.write(data)

	def write_eof(self):
		print('write_eof')
		"""Close the write end after flushing buffered data.
		(This is like typing ^D into a UNIX program reading from stdin.)
		Data may still be received.
		"""
		self.comms.out_q.put_nowait(None)

	def can_write_eof(self):
		print('can_write_eof')
		"""Return True if this transport supports write_eof(), False if not."""
		return True

	def abort(self):
		print('abort')
		"""Close the transport immediately.
		Buffered data will be lost.  No more data will be received.
		The protocol's connection_lost() method will (eventually) be
		called with None as its argument.
		"""
		self.conn.close()
	
async def main():
	from wsnet.pyodide.test_js import js, to_js, create_proxy

	try:
		reader, writer = await open_connection('google.com', 443, ssl=True)
		writer.write(b'GET / HTTP/1.1\r\nHost: google.com\r\n\r\n\r\n')
		await writer.drain()
		data = await reader.read(1024)
		print('Received: {}'.format(data))
	except Exception as e:
		print('Exception: {}'.format(e))
		traceback.print_exc()


if __name__ == '__main__':
	import logging
	#logging.basicConfig(level=logging.DEBUG)

	asyncio.run(main(), debug=True)