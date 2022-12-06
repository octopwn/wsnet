import traceback
import asyncio

import os
from wsnet import logger
from aiosmb.commons.connection.factory import SMBConnectionFactory
from aiosmb.commons.interfaces.file import SMBFile

from asysocks.protocol.socks5 import SOCKS5Command, SOCKS5AddressType, \
	SOCKS5Method, SOCKS5Nego, SOCKS5NegoReply, SOCKS5Request, \
	SOCKS5Reply, SOCKS5ReplyType, SOCKS5PlainAuth, \
	SOCKS5PlainAuthReply, SOCKS5ServerErrorReply, SOCKS5AuthFailed
import logging
from wsnet.protocol import *

class WSNETSMBPipe:
	def __init__(self, pipe):
		self.pipe = pipe
	
	async def terminate(self):
		await self.pipe.close()

	async def recv(self):
		try:
			while True:
				len_raw, err = await self.pipe.read(4)
				if err is not None:
					raise err
					
				length = int.from_bytes(len_raw, byteorder='big', signed=False)
				data, err = await self.pipe.read(length)
				if err is not None:
					raise err
				
				data = len_raw + data
				cmd = CMD.from_bytes(data)
				if cmd.type == CMDType.NOP:
					await asyncio.sleep(0)
					continue
				return cmd
		except Exception as e:
			traceback.print_exc()
			return None

class WSNETPipeSocksServer:
	def __init__(self, smbconfactory, pipename, listen_ip = '127.0.0.1', listen_port = 1080):
		self.smbconfactory = smbconfactory
		self.pipename = pipename
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.clients = {}
		self.client_timeout = 5

	async def outgoing_proxy(self, transport, writer):
		try:
			while True:
				cmd = await transport.recv()
				if cmd.type == CMDType.ERR:
					raise Exception('Connection failed, proxy sent error. Err: %s' % cmd.reason)
				elif cmd.type == CMDType.OK:
					return
				elif cmd.type == CMDType.SD:
					print('[%s] Sending data %s' % (cmd.token, len(cmd.data)))
					writer.write(cmd.data)
					await writer.drain()
				
		except Exception as e:
			traceback.print_exc()
		finally:
			writer.close()

	async def __create_transport(self):
		try:
			
			smbpipe = SMBFile.from_pipename(self.smbconn, self.pipename)
			_, err = await smbpipe.open_pipe(self.smbconn, 'rw')
			if err is not None:
				raise err
				
			return WSNETSMBPipe(smbpipe), None
		except Exception as e:
			return None, e
		

	async def handle_socks5(self, init_cmd, reader, writer):
		token = os.urandom(16)
		try:
			transport, err = await self.__create_transport()
			if err is not None:
				raise err
			
			
			if SOCKS5Method.NOAUTH not in init_cmd.METHODS:
				reply = SOCKS5NegoReply.construct(SOCKS5Method.NOTACCEPTABLE)
				writer.write(reply.to_bytes())
				await writer.drain()
				return
			
			reply = SOCKS5NegoReply.construct(SOCKS5Method.NOAUTH)
			writer.write(reply.to_bytes())
			await writer.drain()

			
			
			req = await asyncio.wait_for(SOCKS5Request.from_streamreader(reader), timeout = self.client_timeout)
			if req.CMD != SOCKS5Command.CONNECT:
				raise Exception('Only CONNECT is supported for now')

			print('[SOCKS5] Client wants to connect to: %s:%s' % (str(req.DST_ADDR), req.DST_PORT))
			try:
				cmd = WSNConnect(token, 'TCP', req.DST_ADDR, req.DST_PORT)
				_, err = await transport.pipe.write(cmd.to_bytes())
				if err is not None:
					raise err
				cmd = await transport.recv()
				if cmd.type == CMDType.ERR:
					raise Exception('Connection failed, proxy sent error. Err: %s' % cmd.reason)

				elif cmd.type != CMDType.CONTINUE:
					raise Exception('Connection failed, expected CONTINUE, got %s' % cmd.type.value)
							
			except Exception as e:
				print('[SOCKS5] Could not connect to: %s:%s Reason: %s' % (str(req.DST_ADDR), req.DST_PORT, e))
				reply = SOCKS5Reply.construct(SOCKS5ReplyType.FAILURE, str(req.DST_ADDR), req.DST_PORT) #TODO: support more error types to let the client know what exscatly went wrong
				writer.write(reply.to_bytes())
				await writer.drain()
				return
			
			print('[SOCKS5] Sucsessfully connected to: %s:%s Starting TCP proxy' % (str(req.DST_ADDR), req.DST_PORT))
			reply = SOCKS5Reply.construct(SOCKS5ReplyType.SUCCEEDED, str(req.DST_ADDR), req.DST_PORT)
			writer.write(reply.to_bytes())
			await writer.drain()
			x = asyncio.create_task(self.outgoing_proxy(transport, writer))

			while not writer.is_closing():
				chunk = await reader.read(60000)
				if chunk == b'':
					break
				cmd = WSNSocketData(token, chunk)
				_, err = await transport.pipe.write(cmd.to_bytes())
				if err is not None:
					raise err

			#sendong ok
			cmd = WSNOK(token)
			_, err = await transport.pipe.write(cmd.to_bytes())

		except Exception as e:
			traceback.print_exc()
			if transport is not None:
				cmd = WSNErr(token, 'Connection terminated!')
				_, err = await transport.pipe.write(cmd.to_bytes())
		finally:
			print('Connection closed!')

	async def handle_client(self, reader, writer):
		try:
			remote_ip, remote_port = writer.get_extra_info('peername')
			logger.info('Client connected from %s:%d' % (remote_ip, remote_port))
			
			try:
				temp = await asyncio.wait_for(reader.readexactly(1), timeout = self.client_timeout)
			except asyncio.exceptions.IncompleteReadError as err:
				logging.debug('Client terminated the socket before socks/http proxy handshake')
				return

			if temp == b'\x04':
				#if 'SOCKS4' not in self.supported_protocols:
				raise Exception('Client tried to use SOCKS4, but it is disabled on the server')
				
				#temp2 = await asyncio.wait_for(reader.readexactly(7), timeout = self.client_timeout)
				#rest = await asyncio.wait_for(reader.readuntil(b'\x00'), timeout = self.client_timeout)
				#init_cmd = SOCKS4Request.from_bytes(temp + temp2+ rest)
				#await self.handle_socks4(init_cmd, reader, writer)
				#return

			elif temp == b'\x05':
				#socks5
				#if 'SOCKS5' not in self.supported_protocols:
				#	raise Exception('Client tried to use SOCKS5, but it is disabled on the server')
				nmethods = await asyncio.wait_for(reader.readexactly(1), timeout = self.client_timeout)
				t_nmethods = int.from_bytes(nmethods, byteorder = 'big', signed = False)
				methods = await asyncio.wait_for(reader.readexactly(t_nmethods), timeout = self.client_timeout)
				init_cmd = SOCKS5Nego.from_bytes(temp + nmethods + methods)
				await self.handle_socks5(init_cmd, reader, writer)
				return
		except Exception as e:
			traceback.print_exc()

	async def run(self):
		try:
			err = None
			if isinstance(self.smbconfactory, str):
				self.smbconfactory = SMBConnectionFactory.from_url(self.smbconfactory)
				self.smbconn = self.smbconfactory.get_connection()
				_, err = await self.smbconn.login()
				if err is not None:
					raise err
				
				temp, err = await self.__create_transport()
				try:
					await temp.terminate()
				except:
					pass
				if err is not None:
					raise err
				
			if err is None:
				server = await asyncio.start_server(self.handle_client, self.listen_ip, self.listen_port)
				await server.serve_forever()

		except Exception as e:
			traceback.print_exc()


async def amain(args):
	try:
		server = WSNETPipeSocksServer(args.smburl, args.pipename, listen_ip=args.ip, listen_port=args.port)
		await server.run()

	except:
		traceback.print_exc()

def main():
	import argparse
	import logging
	parser = argparse.ArgumentParser(description='SOCKS proxy over SMB pipes')
	parser.add_argument('--ip', default='127.0.0.1', help='Listen IP')
	parser.add_argument('--port', type=int, default=1080, help='Listen port')
	parser.add_argument('-v', '--verbose', action='count', default=0, help='Increase verbosity, can be stacked')
	parser.add_argument('smburl', help='smburl')
	parser.add_argument('pipename',  help='pipename')

	args = parser.parse_args()
	if args.verbose == 1:
		logger.setLevel(logging.DEBUG)
			
	elif args.verbose > 1:
		logging.basicConfig(level=1)
		logger.setLevel(logging.DEBUG)

	asyncio.run(amain(args))

if __name__ == '__main__':
	main()
