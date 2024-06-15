import io

def readBytes(buff):
	strlen = int.from_bytes(buff.read(4), byteorder='big', signed = False)
	data = buff.read(strlen)
	return data

def writeBytes(buff, data):
	dlen = len(data).to_bytes(4, byteorder='big', signed = False)
	buff.write(dlen)
	buff.write(data)

def readStr(buff, encoding='utf-8'):
	strlen = int.from_bytes(buff.read(4), byteorder='big', signed = False)
	data = buff.read(strlen).decode(encoding)
	return data

def writeStr(buff, data, encoding='utf-8'):
	if isinstance(data, str) is False:
		data = str(data)
	data = data.encode(encoding)
	dlen = len(data).to_bytes(4, byteorder='big', signed = False)
	buff.write(dlen)
	buff.write(data)