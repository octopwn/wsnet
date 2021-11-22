import websockets
import asyncio
import os
import io
import traceback
import datetime
import logging

from wsnet import logger
from wsnet.protocol import *

class WSNETRouter:
	def __init__(self, out_q, in_q, signal_q_in, signal_q_out, listen_ip = '0.0.0.0', listen_port = 8901, ssl_ctx = None):
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.ssl_ctx = ssl_ctx
		self.wsserver = None
		self.clients = {}
		self.out_q = out_q
		self.in_q = in_q
		self.signal_q_in = signal_q_out
		self.signal_q_out = signal_q_in

	async def __handle_signal_in_queue(self):

		while True:
			data = await self.signal_q_in.get()
			print('AGENT SIGNAL IN! %s' % data)

	async def __handle_in_queue(self):
		while True:
			res = await self.in_q.get()
			try:
				agentid, data = res
				#print('AGENT DATA SEND %s' % data)
				await self.clients[agentid].send(data)
			except Exception as e:
				logger.exception('failed sending agent data!')
	

	async def handle_client(self, ws, path):
		agentid = None
		try:
			agentid = os.urandom(16)
			self.clients[agentid] = ws
			remote_ip, remote_port = ws.remote_address
			logger.info('AGENT connected from %s:%d' % (remote_ip, remote_port))
			while True:
				try:
					data = await ws.recv()
					#print('AGENT DATA RECV %s' % data)
					token = data[6:22]
					if token == b'\x00'*16:
						reply = CMD.from_bytes(data)
						await self.signal_q_out.put(('AGENTIN', agentid, reply))
						continue
					
					await self.out_q.put((agentid, token, data))
				except Exception as e:
					logger.exception('Error in agent handling')
					return
		except Exception as e:
			traceback.print_exc()
		finally:
			if agentid in self.clients:
				del self.clients[agentid]
				await self.signal_q_out.put(('AGENTOUT', agentid, None))
			await ws.close()

	async def run(self):
		asyncio.create_task(self.__handle_in_queue())
		self.wsserver = await websockets.serve(self.handle_client, self.listen_ip, self.listen_port, ssl=self.ssl_ctx)
		await self.wsserver.wait_closed()
		print('Agent handler exiting')

class OPServer:
	def __init__(self, in_q, out_q, signal_q_in, signal_q_out, listen_ip = '0.0.0.0', listen_port = 8900, ssl_ctx = None, reverse_operators = []):
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.ssl_ctx = ssl_ctx
		self.wsserver = None
		self.agents = {}
		self.operators = {}
		self.reverse_operators = reverse_operators #list of WS URLS where the router connects to for external operators
		self.in_q = in_q
		self.out_q = out_q
		self.data_lookop = {}
		self.signal_q_in = signal_q_in
		self.signal_q_out = signal_q_out

	async def __handle_reverse_operator(self, url):
		while True:
			try:
				print('Connecting to remote operator')
				async with websockets.connect(url) as ws:
					await self.handle_client(ws, 'external')
					await asyncio.sleep(1000)
			except Exception as e:
				traceback.print_exc()
			finally:
				await asyncio.sleep(5)
				print('Reconnecting')

				
	async def __handle_signal_in_queue(self):
		while True:
			try:
				data = await self.signal_q_in.get()
				msg, agentid, data = data
				#print('OP SIGNAL IN! %s' % msg)
				if msg == 'AGENTIN':
					print('NEW AGENT : %s' % agentid.hex())
					self.agents[agentid] = data
					agentnotify = WSNListAgentsReply(
						b'\x00'*16,
						agentid,
						data.pid, 
						data.username, 
						data.domain, 
						data.logonserver, 
						data.cpuarch, 
						data.hostname,
						data.usersid,
					)
					for opid in self.operators:
						try:
							#print(agentnotify.to_bytes())
							await self.operators[opid].send(agentnotify.to_bytes())
						except Exception as e:
							del self.operators[opid]
							#traceback.print_exc()

				elif msg == 'AGENTOUT':
					if agentid in self.agents:
						del self.agents[agentid]
			except Exception as e:
				traceback.print_exc()

	async def __handle_in_queue(self):
		while True:
			res = await self.in_q.get()
			try:
				#print('OP DATA IN %s' % repr(res))
				agentid, token, data = res
				tid = agentid+token
				if tid in self.data_lookop:
					try:
						await self.data_lookop[tid].send(data)
					except:
						# currently there is no tracking if the operator has disappeared
						del self.data_lookop[tid]
				else:
					print('TID NOT FOUND!')
					print('TOKEN:   %s' % token)
					print('AGENTID: %s' % agentid)
			except Exception as e:
				logger.exception('OP __handle_in_queue')

	async def handle_client(self, ws, path):
		opid = None
		try:
			opid = os.urandom(16)
			self.operators[opid] = ws
			remote_ip, remote_port = ws.remote_address
			logger.info('Operator connected from %s:%d' % (remote_ip, remote_port))
			while True:
				data = await ws.recv()
				#print(data)
				agentid = data[4:20]
				agentdata = data[20:]
				token = data[26:42]
				#print('agentid:   %s' % agentid)
				#print('token:     %s' % token)
				#print('agentdata: %s' % agentdata)

				if token == b'\x00'*16 and agentid == b'\x00'*16:
					cmd = CMD.from_bytes(agentdata)
					#print(cmd.type)
					if cmd.type == CMDType.LISTAGENTS:
						for agentid in self.agents:
							agentinfo = self.agents[agentid]
							reply = WSNListAgentsReply(
								cmd.token,
								agentid,
								agentinfo.pid, 
								agentinfo.username, 
								agentinfo.domain, 
								agentinfo.logonserver, 
								agentinfo.cpuarch, 
								agentinfo.hostname,
								agentinfo.usersid
							)
							#print('Sending: %s' % reply.to_bytes())
							await ws.send(reply.to_bytes())
						ok = WSNOK(token)
						await ws.send(ok.to_bytes())
					continue
				
				if agentid not in self.agents:
					err = WSNErr(token, "Agent not found", "")
					await ws.send(err.to_bytes())
					continue

				self.data_lookop[agentid+token] = ws
				
				await self.out_q.put((agentid, agentdata))
		
		except Exception as e:
			traceback.print_exc()
			print('OPERATOR DISCONNECTED!')
		finally:
			if opid in self.operators:
				del self.operators[opid]

	async def run(self):
		asyncio.create_task(self.__handle_signal_in_queue())
		asyncio.create_task(self.__handle_in_queue())
		if self.reverse_operators is not None and len(self.reverse_operators) > 0:
			for url in self.reverse_operators:
				asyncio.create_task(self.__handle_reverse_operator(url))
		
		self.wsserver = await websockets.serve(self.handle_client, self.listen_ip, self.listen_port, ssl=self.ssl_ctx)
		await self.wsserver.wait_closed()

async def amain(args):
	#logging.basicConfig(level=logging.DEBUG)

	clientsrv_task = None
	opsrv_task = None

	try:
		signal_q_in = asyncio.Queue()
		signal_q_out = asyncio.Queue()
		in_q = asyncio.Queue()
		out_q = asyncio.Queue()
		clientsrv = WSNETRouter(in_q, out_q, signal_q_in, signal_q_out, listen_ip = args.agent_ip, listen_port = args.agent_port)
		opsrv = OPServer(in_q, out_q, signal_q_in, signal_q_out, listen_ip = args.server_ip, listen_port = args.server_port, reverse_operators=args.rop)
		clientsrv_task = asyncio.create_task(clientsrv.run())
		await opsrv.run()
		

	except Exception as e:
		traceback.print_exc()

def main():
	import argparse

	parser = argparse.ArgumentParser(description='wsnetws router server')
	parser.add_argument('--server-ip', default='0.0.0.0', help = 'server listen ip')
	parser.add_argument('--server-port', default = 8900, type=int, help = 'server listen port')
	parser.add_argument('--agent-ip', default='0.0.0.0', help = 'server listen ip')
	parser.add_argument('--agent-port', default = 8901, type=int, help = 'server listen port')
	parser.add_argument('--rop', action='append', help = 'Connect to operator at given URL')

	args = parser.parse_args()
	print(args.rop)

	asyncio.run(amain(args))

if __name__ == '__main__':
	main()