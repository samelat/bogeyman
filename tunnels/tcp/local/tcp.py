
import json
import struct
import asyncio


class TCP(asyncio.Protocol):

    def __init__(self):
        self.hostname = '127.0.0.1'
        self.port = 8888
        self.adapter = None
        self.loop = None
        self.writer = None

    def set_peer(self, peer):
        self.adapter = peer

    def dispatch(self, message):
        print('[!] RawTunnel receive message <{}>'.format(message))
        data = json.dumps(message).encode()
        self.writer.write(struct.pack('>H', len(data)) + data)

    '''
    def start(self, loop):
        # Each client connection will create a new protocol instance
        self.loop = loop
        handler = loop.create_server(lambda: Handler(self), self.hostname, self.port)
        server = loop.run_until_complete(handler)
        print('[!] Tunnel listening on {}:{}'.format(self.hostname, self.port))
        return server
    '''
    @asyncio.coroutine
    def handler(self, reader, writer):
        print('[!] Tunnel connection ready')
        self.writer = writer
        while True:
            try:
                data = yield from reader.readexactly(2)
                size = struct.unpack('>H', data)[0]
                data = yield from reader.readexactly(size)
                print('[!] Read data: {}'.format(data))

            except asyncio.streams.IncompleteReadError:
                self.writer = None
                print('[!] Tunnel disconnected')
                break

            message = json.loads(data.decode('ascii'))

            print('[!] Incoming message: {}'.format(message))
            self.adapter.dispatch(message)

        print('[!] Tunnel connection, lost')

    def start(self, loop):
        self.loop = loop
        handler = asyncio.start_server(self.handler, self.hostname, self.port, loop=loop)
        server = loop.run_until_complete(handler)
        print('[!] Tunnel listening on {}'.format(server.sockets[0].getsockname()))
        return server

