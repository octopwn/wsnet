import traceback
import websockets
import asyncio
import ssl

from wsnet import logger
from aiosmb.commons.connection.factory import SMBConnectionFactory
from aiosmb.commons.interfaces.file import SMBFile

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
				return data
		except Exception as e:
			traceback.print_exc()
			return None

class WSNETWS2SMBServer:
	def __init__(self, smbfactory, pipename, listen_ip = '127.0.0.1', listen_port = 8700, ssl_ctx = None):
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.ssl_ctx = ssl_ctx
		self.wsserver = None
		self.smbconfactory = smbfactory
		self.pipename = pipename
		self.clients = {}


	async def __create_transport(self):
		try:
			
			smbpipe = SMBFile.from_pipename(self.smbconn, self.pipename)
			_, err = await smbpipe.open_pipe(self.smbconn, 'rw')
			if err is not None:
				raise err
				
			return WSNETSMBPipe(smbpipe), None
		except Exception as e:
			return None, e


	async def incoming_proxy(self, ws, transport):
		try:
			while True:
				data = await transport.recv()
				await ws.send(data)

		except Exception as e:
			traceback.print_exc()
			return

	async def handle_client(self, ws, path):
		transport = None
		inproxy_task = None
		try:
			remote_ip, remote_port = ws.remote_address
			logger.info('Client connected from %s:%d' % (remote_ip, remote_port))
			transport, err = await self.__create_transport()
			if err is not None:
				raise err
			
			inproxy_task = asyncio.create_task(self.incoming_proxy(ws, transport))
			while ws.open:
				data = await ws.recv()
				await transport.pipe.write(data)		
		
		except Exception as e:
			traceback.print_exc()
			return
		finally:
			if transport is not None:
				await transport.terminate()
			if inproxy_task is not None:
				inproxy_task.cancel()

	async def run(self):
		try:
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
				self.wsserver = await websockets.serve(self.handle_client, self.listen_ip, self.listen_port, ssl=self.ssl_ctx)
				await self.wsserver.wait_closed()
		except Exception as e:
			traceback.print_exc()
			return

async def amain(args):
	try:
		ssl_ctx = None
		if args.ssl_cert is not None:
			ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
			if args.ssl_key is None:
				raise Exception('TLS certificate is set but no keyfile!')
			ssl_ctx.load_cert_chain(args.ssl_cert, args.ssl_key)
			if args.ssl_ca is not None:
				ssl_ctx.load_verify_locations(args.ssl_ca)
				ssl_ctx.verify_mode = ssl.CERT_REQUIRED

		server = WSNETWS2SMBServer(args.smburl, args.pipename, listen_ip=args.ip, listen_port=args.port, ssl_ctx=ssl_ctx)
		await server.run()

	except:
		traceback.print_exc()

def main():
	import argparse
	import logging
	parser = argparse.ArgumentParser(description='WSNET proxy server tunnel via SMB pipe')
	parser.add_argument('--ip', default='127.0.0.1', help='Listen IP')
	parser.add_argument('--port', type=int, default=8700, help='Listen port')
	parser.add_argument('-v', '--verbose', action='count', default=0, help='Increase verbosity, can be stacked')
	parser.add_argument('--ssl-cert', help='Certificate file for SSL')
	parser.add_argument('--ssl-key',  help='Key file for SSL')
	parser.add_argument('--ssl-ca',  help='CA cert file for client cert validations')
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
