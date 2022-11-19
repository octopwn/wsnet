import traceback
import websockets
import asyncio
import ssl

from wsnet import logger
from wsnet.agent.agent import WSNETAgent



class WSNETWSServer:
	def __init__(self, listen_ip = '127.0.0.1', listen_port = 8700, ssl_ctx = None):
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.ssl_ctx = ssl_ctx
		self.wsserver = None
		self.clients = {}

	async def handle_client(self, ws, path):
		remote_ip, remote_port = ws.remote_address
		logger.info('Client connected from %s:%d' % (remote_ip, remote_port))
		client = WSNETAgent(ws)
		self.clients[client] = 1
		await client.run()
		await client.terminate()

	async def run(self):
		self.wsserver = await websockets.serve(self.handle_client, self.listen_ip, self.listen_port, ssl=self.ssl_ctx)
		await self.wsserver.wait_closed()


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

		server = WSNETWSServer(listen_ip=args.ip, listen_port=args.port, ssl_ctx=ssl_ctx)
		await server.run()

	except:
		traceback.print_exc()

def main():
	import argparse
	import logging
	parser = argparse.ArgumentParser(description='WSNET proxy server')
	parser.add_argument('--ip', default='127.0.0.1', help='Listen IP')
	parser.add_argument('--port', type=int, default=8700, help='Listen port')
	parser.add_argument('-v', '--verbose', action='count', default=0, help='Increase verbosity, can be stacked')
	parser.add_argument('--ssl-cert', help='Certificate file for SSL')
	parser.add_argument('--ssl-key',  help='Key file for SSL')
	parser.add_argument('--ssl-ca',  help='CA cert file for client cert validations')

	args = parser.parse_args()
	if args.verbose == 1:
		logger.setLevel(logging.DEBUG)
			
	elif args.verbose > 1:
		logging.basicConfig(level=1)
		logger.setLevel(logging.DEBUG)

	asyncio.run(amain(args))

if __name__ == '__main__':
	main()
