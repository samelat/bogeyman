
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
        if self.writer is None:
            return True
        logging.debug('receive message {}'.format(message))
        data = json.dumps(message).encode()
        self.writer.write(struct.pack('>H', len(data)) + data)
        return False

    @asyncio.coroutine
    def handler(self, reader, writer):
        logging.info('connection ready')

        self.writer = writer
        while True:
            try:
                data = yield from reader.readexactly(2)
                size = struct.unpack('>H', data)[0]
                data = yield from reader.readexactly(size)

            except asyncio.streams.IncompleteReadError:
                self.writer = None
                logging.info('disconnected')
                break

            message = json.loads(data.decode('ascii'))

            logging.debug('incoming message {}'.format(message))
            self.adapter.dispatch(message)

        logging.info('connection lost')

    # Keeps connecting with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while True:
            logging.info('connecting to {}:{}'.format(self.host, self.port))
            try:
                connect_coro = asyncio.open_connection(self.host, self.port, loop=self.loop)
                reader, writer = yield from asyncio.wait_for(connect_coro, 8.0)
                yield from self.handler(reader, writer)

            except asyncio.TimeoutError:
                logging.info('connection timeout')

            except ConnectionRefusedError:
                logging.info('connection refused')
                yield from asyncio.sleep(4.0)

            except Exception as e:
                logging.error('unknown tunnel exception: {}'.format(e))
                yield from self.stop()
                break

    @asyncio.coroutine
    def stop(self):
        if self.reverse:
            self.tunnel.close()
            sys.stdout.flush()
            try:
                yield from asyncio.wait_for(self.tunnel.wait_closed(), 2.0, loop=self.loop)
            except asyncio.TimeoutError:
                pass

        self.adapter.dispatch({'cmd': 'stop'})

    def start(self, loop):
        self.loop = loop

        if self.reverse:
            server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=loop)
            self.tunnel = loop.run_until_complete(server_coroutine)
            logging.info('listening on {}:{}'.format(self.host, self.port))

        else:
            self.tunnel = asyncio.async(self.connect(), loop=loop)
