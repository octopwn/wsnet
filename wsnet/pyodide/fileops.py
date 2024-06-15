import asyncio
import os
import json
from wsnet.protocol import *
import contextlib
import traceback

try:
	import js
	from pyodide.ffi import to_js
	from pyodide.ffi import create_proxy
except:
	pass

class WSNETSession:
	def __init__(self, connect_timeout=5, read_timeout = 5, write_timeout = 5):
		self.token = os.urandom(16)
		self.read_timeout = read_timeout
		self.write_timeout = write_timeout
		self.connect_timeout = connect_timeout
		self.reuse_ws = True
		self.connected_evt = asyncio.Event()
		self.disconnected_evt = asyncio.Event()
		self.internal_in_q = asyncio.Queue()
		self.connected_evt_proxy = create_proxy(self.connected_evt)
		self.disconnected_evt_proxy = create_proxy(self.disconnected_evt)
		self.data_in_proxy = create_proxy(self.internal_in_q)
		self.ws_url = js.document.getElementById('proxyurl')
		self.ws = None

	async def __aenter__(self):
		await self.setup()
		return self
	
	async def __aexit__(self, exc_type, exc, tb):
		await self.disconnect()

	async def disconnect(self):
		await self.send_ok(self.token)
		if self.ws is not None:
			js.deleteWebSocket(self.ws)
		self.ws = None
		if self.disconnected_evt is not None:
			self.disconnected_evt.set()
	
	async def send_ok(self, token):
		cmd = WSNOK(token)
		await self.send(cmd)
	
	async def setup(self):
		self.ws = js.createNewWebSocket(str(self.ws_url.value), self.connected_evt_proxy, self.data_in_proxy, self.disconnected_evt_proxy, self.reuse_ws, to_js(self.token))
		await asyncio.wait_for(self.connected_evt.wait(), self.connect_timeout)
		
	async def send(self, cmd):
		js.sendWebSocketData(self.ws, cmd.to_bytes())

	async def recv(self):
		data_memview = await asyncio.wait_for(self.internal_in_q.get(), self.read_timeout)
		return CMD.from_bytes(data_memview.to_py())

class WSNETFile:
	def __init__(self):
		self.session = None
		self.mode = None
		self.offset = 0
		self.size = 0
		self.__chunk_size = 1024 * 1024


	async def __aenter__(self):
		return self
	
	async def __aexit__(self, exc_type, exc, tb):
		await self.close()
	
	async def close(self):
		await self.session.send_ok(self.session.token)
	
	@staticmethod
	async def open(path, mode):
		file = WSNETFile()
		file.session = WSNETSession()
		await file.session.setup()
		cmd = WSNFileOpen(file.session.token, path, mode)
		await file.session.send(cmd)
		while True:
			cmd = await file.session.recv()
			if cmd.type == CMDType.ERR:
				raise Exception(cmd.reason)
			elif cmd.type == CMDType.CONTINUE:
				break
		file.mode = mode
		if 'r' in mode:
			await file.fstat()
		return file
	
	async def fstat(self):
		cmd = WSNFileStat(self.session.token)
		await self.session.send(cmd)
		while True:
			cmd = await self.session.recv()
			if cmd.type == CMDType.ERR:
				raise Exception(cmd.reason)
			elif cmd.type == CMDType.FILEENTRY:
				break
		self.size = cmd.size
		return cmd
	
	async def __read(self, size):
		while size > 0:
			reqsize = min(size, self.__chunk_size)
			cmd = WSNFileRead(self.session.token, reqsize, offset= self.offset)
			await self.session.send(cmd)
			while True:
				cmd = await self.session.recv()
				if cmd.type == CMDType.ERR:
					raise Exception(cmd.reason)
				elif cmd.type == CMDType.FILEDATA:
					if cmd.data == b'':
						raise Exception('EOF')
					self.offset += len(cmd.data)
					size -= len(cmd.data)
					yield cmd.data
					break
	
	async def tell(self):
		return self.offset
	
	async def seek(self, offset, whence = 0):
		if whence == 0:
			self.offset = offset
		elif whence == 1:
			self.offset += offset
		elif whence == 2:
			if offset > 0:
				raise Exception('Seeking from end is only supported for negative offsets')
			if self.size is None or self.size == 0:
				raise Exception('Seeking from end is not supported for files with unknown size')
			self.offset = self.size + offset
		else:
			raise Exception('Invalid whence')

	async def read(self, n = -1):
		if 'r' not in self.mode:
			raise Exception('File not opened in read mode')
		if n == -1:
			n = self.size - self.offset
		if n == 0 or self.offset >= self.size:
			return b''
		if self.offset + n > self.size:
			n = self.size - self.offset
		data = b''
		async for d in self.__read(n):
			data += d
		return data
	
	async def write(self, data):
		try:
			if isinstance(data, str):
				data = data.encode()
			if not isinstance(data, (bytearray, bytes)):
				data = data.to_py()

			if 'w' not in self.mode:
				raise Exception('File not opened in write mode')
			while len(data) > 0:
				dsize = min(len(data), self.__chunk_size)
				tdata = data[:dsize]
				cmd = WSNFileData(self.session.token, tdata, offset= self.offset)
				await self.session.send(cmd)
				while True:
					cmd = await self.session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.CONTINUE:
						break
				self.offset += len(tdata)
				data = data[len(tdata):]
			return len(data)
		except Exception as e:
			traceback.print_exc()

class WSNETFileOps:
	def __init__(self):
		pass

	async def __aenter__(self):
		return self
	
	async def __aexit__(self, exc_type, exc, tb):
		return

	async def disconnect(self):
		return
	
	def joinpath(self, root, name):
		if not root.startswith('/'):
			root = root[1:]
		if root.endswith('/'):
			return root + name
		return root + '/' + name
	
	async def ls(self, path):
		try:
			entries = []
			async with WSNETSession() as session:
				cmd = WSNDirLS(session.token, path)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						break
					elif cmd.type == CMDType.FILEENTRY:
						entries.append(cmd.to_dict())
			return json.dumps(entries)
		except Exception as e:
			raise e
	
	async def walk(self, path):
		try:
			async with WSNETSession() as session:
				cmd = WSNDirLS(session.token, path)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						break
					elif cmd.type == CMDType.FILEENTRY:
						yield cmd, None
		
		except Exception as e:
			yield None, e

	async def rmdir(self, path):
		try:
			async with WSNETSession() as session:
				cmd = WSNDirRM(session.token, path)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	async def mkdir(self, path):
		try:
			async with WSNETSession() as session:
				cmd = WSNDirMK(session.token, path)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	async def copydir(self, srcpath, dstpath):
		try:
			async with WSNETSession() as session:
				cmd = WSNDirCopy(session.token, srcpath, dstpath)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	async def movedir(self, srcpath, dstpath):
		try:
			async with WSNETSession() as session:
				cmd = WSNDirMove(session.token, srcpath, dstpath)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
		
	async def copyfile(self, srcpath, dstpath):
		try:
			async with WSNETSession() as session:
				cmd = WSNFileCopy(session.token, srcpath, dstpath)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	async def movefile(self, srcpath, dstpath):
		try:
			async with WSNETSession() as session:
				cmd = WSNFileMove(session.token, srcpath, dstpath)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	async def removefile(self, path):
		try:
			async with WSNETSession() as session:
				cmd = WSNFileRM(session.token, path)
				await session.send(cmd)
				while True:
					cmd = await session.recv()
					if cmd.type == CMDType.ERR:
						raise Exception(cmd.reason)
					elif cmd.type == CMDType.OK:
						return True, None
		
		except Exception as e:
			return None, e
	
	@staticmethod
	@contextlib.asynccontextmanager
	async def open(path, mode):
		file = await WSNETFile.open(path, mode)
		try:
			yield file
		finally:
			await file.close()
	
	@staticmethod
	async def openfile(path, mode):
		return await WSNETFile.open(path, mode)
	
async def amain():
	async with WSNETFileOps() as fileops:
		print(await fileops.mkdir('/tmp/wsnettest'))

		async for entry, err in fileops.walk('/tmp'):
			if err is not None:
				print(err)
			else:
				print(entry)
		
		
		print(await fileops.rmdir('/tmp/wsnettest'))

		async for entry, err in fileops.walk('/tmp'):
			if err is not None:
				print(err)
			else:
				print(entry)

		await fileops.mkdir('/tmp/wsnettest')
		print(await fileops.copydir('/tmp/wsnettest', '/tmp/wsnettest2'))
		print(await fileops.movedir('/tmp/wsnettest2', '/tmp/wsnettest3'))
		print(await fileops.rmdir('/tmp/wsnettest3'))
		print(await fileops.rmdir('/tmp/wsnettest2'))
		
		print('Creating file')
		async with WSNETFileOps.open('/tmp/wsnettest.txt', 'w') as file:
			await file.write(b'Hello world')
		
		print('Reading file')
		async with WSNETFileOps.open('/tmp/wsnettest.txt', 'r') as file:
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(1))
			print(await file.read(100000))

def main():
	asyncio.run(amain())

if __name__ == '__main__':
	main()