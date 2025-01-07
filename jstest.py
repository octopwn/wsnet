from wsnet.protocol import WSNGetInfo
import os

a = WSNGetInfo(os.urandom(16)).to_bytes()
print({', '.join(str(b) for b in a)})