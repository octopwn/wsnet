import traceback
import websockets
import asyncio
import ssl
import os
import uuid
from typing import Dict
from urllib.parse import urlparse

from wsnet import logger
from wsnet.agent.agent import WSNETAgent
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat
from datetime import datetime, timedelta

WSNET_ALLOWED_ORIGINS = {
	'0.0.0.0' : 1,
	'127.0.0.1' : 1,
	'localhost' : 1,
}


def create_ca(ca_cert_path: str, ca_key_path: str):
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    ca_subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"My Local CA"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert.public_bytes(Encoding.PEM))
    with open(ca_key_path, "wb") as f:
        f.write(ca_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))

    return ca_cert, ca_key


def create_server_cert(ca_cert, ca_key, server_cert_path: str, server_key_path: str):
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    server_subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    
    with open(server_cert_path, "wb") as f:
        f.write(server_cert.public_bytes(Encoding.PEM))
        f.write(ca_cert.public_bytes(Encoding.PEM))
    with open(server_key_path, "wb") as f:
        f.write(server_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))

class WSNETWSServer:
	def __init__(self, listen_ip:str = '127.0.0.1', listen_port:int = 8700, ssl_ctx:ssl.SSLContext = None, secret:str = None, disable_origin_check:bool = False, allowed_origins:Dict[str, int] = WSNET_ALLOWED_ORIGINS, disable_security:bool = False):
		self.listen_ip = listen_ip
		self.listen_port = listen_port
		self.ssl_ctx = ssl_ctx
		self.wsserver = None
		self.clients = {}
		self.disable_origin_check = disable_origin_check
		self.secret = secret
		if self.secret is None or self.secret == '':
			self.secret = str(uuid.uuid4())
		self.allowed_origins = allowed_origins
		self.disable_security = disable_security
		if self.disable_security is True:
			self.secret = None
	
	def validate_client(self, remote_ip:str, remote_port:int, path:str, origin_header:str):
		# Problem is that local websockets server can be reached from any webpage the user might browse to
		# This would allow a malicious page to use this proxy to do nasty things.
		# For this, the following security measurements have been applied:
		# 1. This server can only be reached if via a correct path, otherwise connection will be terminated
		# 2. The initial connection's Origin header must be in the tusted origins list

		if path.replace('/', '') != self.secret:
			raise Exception('Incoming client provided an invalid secret! Terminating connection')
		
		if self.disable_origin_check is True:
			return
		
		if origin_header is None:
			raise Exception('Incoming client did not provide an Origin header! Terminating connection')
		
		parsed_origin = urlparse(origin_header)
		origin = parsed_origin.hostname
		if origin.endswith('.octopwn.com') is True:
			# This is a subdomain of octopwn.com, the site is served from the official server, so we can trust it
			# Concern #1: The static webpage of octopwn can be loaded via HTTP, so a MITM could serve a malicious page
			# Concern #2: Octopwn might be reached via a company proxy that intercepts TLS, which could be malicious
			return
		if origin.lower() not in self.allowed_origins:
			raise Exception('Client provided an invalid Origin header %s! Terminating connection' % origin)
		
	async def handle_client(self, ws, path:str):
		remote_ip, remote_port = ws.remote_address
		raddr = '%s:%d' % (remote_ip, remote_port)
		logger.info('[%s] Client connected' % raddr)

		if self.disable_security is False:
			try:
				self.validate_client(remote_ip, remote_port, path, ws.request_headers.get('Origin', None))
			except Exception as e:
				print('Failed to validate client! Reason: %s' % e)
				return
		
		# Now that the client connection has been validated, we can continue actually initializing the client
		client = WSNETAgent(ws)
		self.clients[client] = 1
		try:
			async for data in ws:
				await client.process_incoming(data)
		except Exception as e:
			logger.info('[%s] Client disconnected' % raddr)
			logger.debug("Websockets client error: %s\n%s", e, traceback.format_exc())
		finally:
			await client.terminate()

	async def run(self):
		self.wsserver = await websockets.serve(self.handle_client, self.listen_ip, self.listen_port, ssl=self.ssl_ctx)
		proto = 'ws'
		if self.ssl_ctx is not None:
			proto = 'wss'
		if self.secret is None:
			print('Listening on %s://%s:%d/' % (proto, self.listen_ip, self.listen_port))
		else:
			print('Listening on %s://%s:%d/%s/' % (proto, self.listen_ip, self.listen_port, self.secret))
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

		server = WSNETWSServer(
			listen_ip=args.ip, 
			listen_port=args.port, 
			ssl_ctx=ssl_ctx, 
			secret = args.secret, 
			disable_origin_check=args.noorigin,
			disable_security=args.disable_security
		)

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
	parser.add_argument('--secret',  type=str, help='Secret string to protect this proxy from malicious connections')
	parser.add_argument('--noorigin', action='store_true', help='Disables origin header validation')
	parser.add_argument('--disable-security', action='store_true', help='Disables all security validations')
	parser.add_argument('--plaintext', action='store_true', help='Disables TLS')

	args = parser.parse_args()
	if args.verbose == 1:
		logger.setLevel(logging.DEBUG)
			
	elif args.verbose > 1:
		logging.basicConfig(level=1)
		logger.setLevel(logging.DEBUG)
	
	if args.plaintext is True:
		args.ssl_cert = None
		args.ssl_key = None
		args.ssl_ca = None
	else:
		if args.ssl_cert is None and args.ssl_key is None:
			#check if cert is already generated
			ca_cert_name = 'octopwn_ca_cert.pem'
			ca_key_name = 'octopwn_ca_key.pem'
			cert_file_name = 'octopwn_ceritficate.pem'
			key_file_name = 'octopwn_key.pem'
			if os.path.exists(cert_file_name) and os.path.exists(key_file_name):
				print('Using existing certificate and key files')
				args.ssl_cert = cert_file_name
				args.ssl_key = key_file_name
				args.ssl_ca = None
			else:
				if os.path.exists(ca_cert_name) and os.path.exists(ca_key_name):
					print('Using existing CA certificate and key files')
					ca_cert = x509.load_pem_x509_certificate(open(ca_cert_name, 'rb').read())
					ca_key = rsa.load_pem_private_key(open(ca_key_name, 'rb').read(), password=None)
				else:
					print('Generating self-signed CA')
					ca_cert, ca_key = create_ca(ca_cert_name, ca_key_name)

				print('Generating self-signed certificate and key files')
				create_server_cert(ca_cert, ca_key, cert_file_name, key_file_name)
				args.ssl_cert = cert_file_name
				args.ssl_key = key_file_name
				args.ssl_ca = None
		elif args.ssl_cert is None or args.ssl_key is None:
			raise Exception('You need to specify both certificate and key files!')

	asyncio.run(amain(args))

if __name__ == '__main__':
	main()
