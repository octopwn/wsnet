import traceback
import websockets
import asyncio

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
		server = WSNETWSServer(listen_ip=args.ip, listen_port=args.port)
		await server.run()

	except:
		traceback.print_exc()

def main():
	import argparse
	import logging
	parser = argparse.ArgumentParser(description='WSNET proxy server')
	parser.add_argument('--ip', default='127.0.0.1', help='Listen IP')
	parser.add_argument('--port', type=int, default=8700, help='Listen port')

	args = parser.parse_args()
	#logger.setLevel(logging.DEBUG)
	asyncio.run(amain(args))

if __name__ == '__main__':
	main()
