import asyncio
import websockets

MOCK_JS_WEBSCOKETTABLE = {}
MOCK_JS_WEBSOCKET_ID = 1
MOCK_WSNET_URL = 'ws://127.0.0.1:8700/'

def to_js(obj):
    return obj

def create_proxy(obj):
    return obj

class MOC_JS_PROXY_BYTES:
    def __init__(self, data):
        self.data = data
    
    def to_py(self):
        return self.data

class jsdocuelement:
    def __init__(self):
        self.value = MOCK_WSNET_URL

class jsdocument:
    def __init__(self):
        self._proxyurl = jsdocuelement()

    @staticmethod
    def getElementById(eid):
        return jsdocuelement()
    


class js:
    def __init__(self):
        self.document = jsdocument()
    
    @staticmethod
    def sendWebSocketData(ws_id, data:bytearray):
        global MOCK_JS_WEBSCOKETTABLE
        MOCK_JS_WEBSCOKETTABLE[ws_id]._in_q.put_nowait(data)

    @staticmethod
    def createNewWebSocket(url, connected_evt, data_in, disconnected_evt, reuse_ws, token):
        print('createNewWebSocket', url, connected_evt, data_in, disconnected_evt, reuse_ws, token)
        global MOCK_JS_WEBSOCKET_ID
        global MOCK_JS_WEBSCOKETTABLE

        wsid = MOCK_JS_WEBSOCKET_ID
        MOCK_JS_WEBSOCKET_ID += 1
        MOCK_JS_WEBSCOKETTABLE[wsid] = MOCK_JS_WSNET_CONNECTION(url, connected_evt, data_in, disconnected_evt, reuse_ws, token)

        x = asyncio.create_task(MOCK_JS_WEBSCOKETTABLE[wsid].run())
        return wsid
    
class MOCK_JS_WSNET_CONNECTION:
    def __init__(self, url, connected_evt, data_in, disconnected_evt, reuse_ws, token):
        self.url = url
        self.connected_evt = connected_evt
        self.data_in = data_in
        self.disconnected_evt = disconnected_evt
        self.reuse_ws = reuse_ws
        self.token = token
        self.out_task = None

        self._in_q = asyncio.Queue()
        self._out_q = asyncio.Queue()

        self.ws = None

    async def stop(self):
        self.disconnected_evt.set()
        self.out_task.cancel()
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def __handle_data_out(self):
        while self.ws.open:
            data = await self._in_q.get()
            await self.ws.send(data)

    async def run(self):
        try:
            self.ws = await websockets.connect(self.url)
            self.out_task = asyncio.create_task(self.__handle_data_out())
            self.connected_evt.set()
            while self.ws.open:
                data = await self.ws.recv()
                await self.data_in.put(MOC_JS_PROXY_BYTES(data))


        except Exception as e:
            print(e)
            await self.stop()