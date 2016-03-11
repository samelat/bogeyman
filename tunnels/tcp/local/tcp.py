
import sys
import json
import struct
import asyncio
import logging


class TCP(asyncio.Protocol):

    def __init__(self, params):
        self.host = params.get('host', '127.0.0.1')
        self.port = int(params.get('port', 8888))
        self.reverse = 'reverse' in params

        self.tunnel = None
        self.adapter = None
        self.loop = None
        self.writer = None

    def set_peer(self, peer):
        self.adapter = peer

    def dispatch(self, message):
        print('[!] RawTunnel receive message <{}>'.format(message))
        data = json.dumps(message).encode()
        self.writer.write(struct.pack('>H', len(data)) + data)

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

        print('[!] Tunnel connection lost')

    # Keeps connecting with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while True:
            logging.info('Tunnel connecting to {}:{}'.format(self.host, self.port))
            try:
                print('BBBBBBB')
                yield from asyncio.open_connection(self.host, self.port, loop=self.loop)
                print('AAAAAAA')
                # reader, writer = yield from asyncio.wait_for(,8.0)
                # reader, writer = yield from asyncio.open_connection(self.host, self.port, loop=self.loop)
                # yield from self.handler(reader, writer)
            except asyncio.TimeoutError:
                logging.info('Tunnel connection timeout')

            except Exception as e:
                logging.error('Unknown tunnel exception: {}'.format(e))
                self.stop()
                break

    def stop(self):
        print('ggggggggggggggg')
        if self.reverse:
            self.tunnel.close()
            self.loop.run_until_complete(self.tunnel.wait_closed())
        else:
            print('CCCCC')
            # self.tunnel.cancel()
            self.adapter.dispatch({'cmd': 'stop'})
            # self.loop.run_until_complete(self.tunnel)

    def start(self, loop):
        self.loop = loop

        if self.reverse:
            server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=loop)
            self.tunnel = loop.run_until_complete(server_coroutine)
            logging.info('Tunnel listening on {}:{}'.format(self.host, self.port))

        else:
            self.tunnel = asyncio.async(self.connect(), loop=loop)
