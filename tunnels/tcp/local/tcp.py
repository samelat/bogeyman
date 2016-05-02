
import json
import time
import struct
import asyncio
import logging


class TCP(asyncio.Protocol):

    def __init__(self, tunnel_ip, tunnel_port, reverse=False):
        self.host = tunnel_ip
        self.port = tunnel_port
        self.reverse = reverse

        self.tunnel = None
        self.adapter = None
        self.loop = None
        self.writer = None
        self.running = False

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
        while self.running:
            try:
                data = yield from reader.readexactly(2)
                size = struct.unpack('>H', data)[0]
                data = yield from reader.readexactly(size)

            except asyncio.streams.IncompleteReadError:
                self.writer = None
                logging.info('disconnected')
                break

            except asyncio.CancelledError:
                self.writer.close()
                break

            message = json.loads(data.decode('ascii'))

            logging.debug('incoming message {}'.format(message))
            self.adapter.dispatch(message)

        logging.info('connection closed')

    # Keeps connecting with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while self.running:
            logging.info('connecting to {}:{}'.format(self.host, self.port))
            try:
                connect_coro = asyncio.open_connection(self.host, self.port, loop=self.loop)
                reader, writer = yield from asyncio.wait_for(connect_coro, 8.0)
                yield from self.handler(reader, writer)

            except asyncio.TimeoutError:
                logging.info('connection timeout')

            except ConnectionRefusedError:
                logging.info('connection refused')
                end_time = time.time() + 8.0
                while self.running and (end_time > time.time()):
                    yield from asyncio.sleep(0.5)

            except asyncio.CancelledError:
                self.running = False

    @asyncio.coroutine
    def wait(self):
        self.running = False
        try:
            if self.reverse:
                self.tunnel.close()
                yield from asyncio.wait_for(self.tunnel.wait_closed(), 2.0, loop=self.loop)
            else:
                self.tunnel.cancel()
                yield from asyncio.wait_for(self.tunnel, 2.0, loop=self.loop)
        except asyncio.TimeoutError:
            pass

    def stop(self):
        self.loop.run_until_complete(self.wait())

    def start(self, loop):
        self.loop = loop
        self.running = True

        if self.reverse:
            server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=loop)
            self.tunnel = loop.run_until_complete(server_coroutine)
            logging.info('listening on {}:{}'.format(self.host, self.port))

        else:
            self.tunnel = asyncio.async(self.connect(), loop=loop)
