
import base64
import struct
import random
import socket
import asyncio
import logging


class Socks5:

    def __init__(self, address, port):
        self.address = address
        self.port = port
        self.tunnel = None

        self.server = None
        self.loop = None
        self.lock = asyncio.Condition()
        self.streams = {}

    def set_peer(self, peer):
        self.tunnel = peer

    @asyncio.coroutine
    def new_connection(self, reader, writer):

        # New connection ID (src address, src port).
        cid = random.getrandbits(32)
        src_info = writer.get_extra_info('peername')
        logging.info('[#{}] connection from: {}:{}'.format(cid, *src_info))

        # Start Socks5 protocol implementation
        data = yield from reader.readexactly(2)
        version, nmethods = struct.unpack('BB', data)
        logging.debug('[#{}] socks version: {} - Number of methods: {}'.format(cid, version, nmethods))

        if version not in [4, 5] or nmethods < 1:
            logging.debug('[#{}] incorrect header information'.format(cid))
            writer.close()
            return

        data = yield from reader.readexactly(nmethods)
        methods = list(data)
        logging.debug('[#{}] suggested auth methods: {}'.format(cid, methods))
        # For now we only accept non-authentication.
        if 0 not in methods:
            logging.debug('[#{}] authentication methods not supported'.format(cid))
            writer.close()
            return

        # Sends first step response.
        writer.write(struct.pack('BB', version, 0))

        # Waits for connection command
        # +----+-----+-------+------+
        # |VER | CMD |  RSV  | ATYP |
        # +----+-----+-------+------+
        data = yield from reader.readexactly(4)
        _, command, _, address_type = struct.unpack('BBBB', data)
        if address_type not in [1, 3]:
            logging.debug('[#{}] address type not supported'.format(cid))
            # +----+-----+-----+------+----------+----------+
            # |VER | REP | RSV | ATYP | BND.ADDR | BND.PORT |
            # +----+-----+-----+------+----------+----------+
            writer.write(struct.pack('>BBBBIH', version, 8, 0, 1, 0, 0))
            writer.close()
            return

        if address_type is 1:
            data = yield from reader.readexactly(6)
            address = socket.inet_ntoa(data[:4])
            port = struct.unpack('>H', data[4:])[0]

        elif address_type is 3:
            data = yield from reader.readexactly(1)
            domain_size = struct.unpack('B', data)[0]
            data = yield from reader.readexactly(domain_size + 2)
            address = data[:domain_size].decode('ascii')
            port = struct.unpack('>H', data[domain_size:])[0]

        # We will implement ipv6 when we need it :P.

        logging.info('[#{}] trying to connect to {}:{}'.format(cid, address, port))
        with (yield from self.lock):
            self.streams[cid] = {'writer': writer, 'status': -1}

        # Once we know where the client wants to connect to, we send the command to the tunnel.
        while self.tunnel.dispatch({'cmd': 'connect', 'addr': address, 'port': port, 'id': cid}):
            yield from asyncio.sleep(1.0)

        # and we wait for the connection's result ...
        with (yield from self.lock):
            while self.streams[cid]['status'] is -1:
                logging.debug('[#{}] waiting until stream status change'.format(cid))
                yield from self.lock.wait()
            reply = self.streams[cid]['status']

        # Sends the command response.
        # The client have to continue using this connection for the stream.
        # +----+-----+-------+------+----------+----------+
        # |VER | REP |  RSV  | ATYP | BND.ADDR | BND.PORT |
        # +----+-----+-------+------+----------+----------+
        writer.write(struct.pack('>BBBBIH', version, reply, 0, 1, 0, 0))

        if reply is not 0:
            writer.close()
            return

        while True:
            try:
                data = yield from reader.read(8192)
            except ConnectionResetError:
                break

            if not data:
                break

            logging.debug('[#{}] received data: {}'.format(cid, repr(data)))

            b64data = base64.b64encode(data).decode('ascii')
            message = {'cmd': 'sync', 'data': b64data, 'id': cid}
            while self.tunnel.dispatch(message):
                yield from asyncio.sleep(1.0)

        logging.debug('Closing connection #{}'.format(cid))
        with (yield from self.lock):
            # We have to control if the writer was not closed by a "disconnect" message first.
            if self.streams[cid]['status'] == 0:
                try:
                    yield from writer.drain()
                except ConnectionResetError:
                    pass
                writer.close()
            del(self.streams[cid])

    @asyncio.coroutine
    def execute(self, message):
        logging.debug('executing message {}'.format(message))
        with (yield from self.lock):
            if message['cmd'] == 'status':
                if message['id'] in self.streams:
                    if message['value'] < 0:
                        try:
                            yield from self.streams[message['id']]['writer'].drain()
                        except ConnectionResetError:
                            pass
                        self.streams[message['id']]['writer'].close()
                    self.streams[message['id']]['status'] = message['value']
                    self.lock.notify_all()

            elif message['cmd'] == 'disconnect':
                if message['id'] in self.streams:
                    yield from self.streams[message['id']]['writer'].drain()
                    self.streams[message['id']]['writer'].close()
                    self.streams[message['id']]['status'] = -2
                    self.lock.notify_all()
                logging.debug('[#{}] disconnected'.format(message['id']))

            elif message['cmd'] == 'sync':
                if message['id'] in self.streams:
                    data = base64.b64decode(message['data'].encode('ascii'))
                    self.streams[message['id']]['writer'].write(data)

            elif message['cmd'] == 'stop':
                self.server.close()
                try:
                    yield from asyncio.wait_for(self.server.wait_closed(), 2.0, loop=self.loop)
                except asyncio.TimeoutError:
                    pass
                self.loop.stop()

    def dispatch(self, message):
        def async_execute(msg):
            asyncio.async(self.execute(msg), loop=self.loop)
        self.loop.call_soon_threadsafe(async_execute, message)

    def stop(self):
        self.server.close()
        self.loop.run_until_complete(self.server.wait_closed())

    def start(self, loop):
        self.loop = loop
        handler = asyncio.start_server(self.new_connection, self.address, self.port, loop=loop)
        self.server = loop.run_until_complete(handler)
        logging.info('listening on {}:{}'.format(self.address, self.port))
