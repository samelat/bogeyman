
import base64
import struct
import random
import socket
import asyncio
import logging
import traceback


class Stream:
    def __init__(self, reader, writer):
        self.logger = logging.getLogger('bogeyman')
        self.id = random.getrandbits(32)
        self.reader = reader
        self.writer = writer
        self.version = 0
        self.status = -1
        self.task = None

    def __del__(self):
        try:
            self.writer.close()
        except RuntimeError:
            pass

    @asyncio.coroutine
    def socks5_handshake(self):
        src_info = self.writer.get_extra_info('peername')
        self.logger.info('[#{}] connection from: {}:{}'.format(self.id, *src_info))

        # Start Socks5 protocol implementation
        data = yield from self.reader.readexactly(2)
        self.version, nmethods = struct.unpack('BB', data)
        self.logger.debug('[#{}] socks version: {} - Number of methods: {}'.format(self.id, self.version, nmethods))

        if self.version not in [4, 5] or nmethods < 1:
            self.logger.debug('[#{}] incorrect header information'.format(self.id))
            return False

        data = yield from self.reader.readexactly(nmethods)
        methods = list(data)
        self.logger.debug('[#{}] suggested auth methods: {}'.format(self.id, methods))
        # By now we only accept non-authentication.
        if 0 not in methods:
            self.logger.debug('[#{}] authentication methods not supported'.format(self.id))
            return False

        # Sends first step response.
        self.writer.write(struct.pack('BB', self.version, 0))
        return True

    @asyncio.coroutine
    def socks5_command(self):
        # Waits for connection command
        # +----+-----+-------+------+
        # |VER | CMD |  RSV  | ATYP |
        # +----+-----+-------+------+
        data = yield from self.reader.readexactly(4)
        _, command, _, address_type = struct.unpack('BBBB', data)
        if address_type not in [1, 3]:
            self.logger.debug('[#{}] address type not supported'.format(self.id))
            # +----+-----+-----+------+----------+----------+
            # |VER | REP | RSV | ATYP | BND.ADDR | BND.PORT |
            # +----+-----+-----+------+----------+----------+
            self.writer.write(struct.pack('>BBBBIH', self.version, 8, 0, 1, 0, 0))
            self.writer.close()
            return None

        if address_type is 1:
            data = yield from self.reader.readexactly(6)
            address = socket.inet_ntoa(data[:4])
            port = struct.unpack('>H', data[4:])[0]

        elif address_type is 3:
            data = yield from self.reader.readexactly(1)
            domain_size = struct.unpack('B', data)[0]
            data = yield from self.reader.readexactly(domain_size + 2)
            address = data[:domain_size].decode('ascii')
            port = struct.unpack('>H', data[domain_size:])[0]

        # We will implement ipv6 when we need it :P.

        self.logger.info('[#{}] trying to connect to {}:{}'.format(self.id, address, port))
        #with (yield from self.lock):
        #    self.streams[self.cid] = {'writer': self.writer, 'status': -1}

        return {'cmd': 'connect', 'addr': address, 'port': port, 'id': self.id}

    @asyncio.coroutine
    def set_status(self, status):
        if self.status == -1:
            # Sends the command execution status.
            # The client have to continue using this connection for the stream.
            # +----+-----+-------+------+----------+----------+
            # |VER | REP |  RSV  | ATYP | BND.ADDR | BND.PORT |
            # +----+-----+-------+------+----------+----------+
            self.writer.write(struct.pack('>BBBBIH', self.version, status, 0, 1, 0, 0))

        self.status = status
        if self.status:
            try:
                yield from self.writer.drain()
            except ConnectionResetError:
                pass
            self.writer.close()


class Socks5:

    def __init__(self, address, port):
        self.logger = logging.getLogger('bogeyman')
        self.address = address
        self.port = port
        self.tunnel = None

        self.server = None
        self.loop = None
        self.lock = asyncio.Condition()
        self.streams = {}
        self.running = False

    def set_peer(self, peer):
        self.tunnel = peer

    @asyncio.coroutine
    def new_connection(self, reader, writer):

        # new stream
        stream = Stream(reader, writer)
        stream.task = asyncio.Task.current_task(loop=self.loop)

        try:
            self.streams[stream.id] = stream

            assert (yield from stream.socks5_handshake())

            command = yield from stream.socks5_command()
            assert command is not None, 'unknown socks5 command'

            # Once we know where the client wants to connect to, we send the command to the tunnel.
            while not self.tunnel.dispatch(command):
                yield from asyncio.sleep(1.0)
                assert self.running, 'aborting stream #{}'.format(stream.id)

            # Wait until the connection status will be established
            # TODO: We have to control how much time has passed before assume it's lost.
            with (yield from self.lock):
                while self.running and (stream.status == -1):
                    self.logger.debug('[#{}] waiting until stream status change'.format(stream.id))
                    yield from self.lock.wait()

            assert self.running and stream.status == 0, 'aborting stream #{}'.format(stream.id)

            # The socks5 connection is done. We can start forwarding data
            while True:
                try:
                    data = yield from reader.read(8192)
                except BrokenPipeError:
                    data = ''

                if not data:
                    break

                self.logger.debug('[#{}] received data: {}'.format(stream.id, repr(data)))

                b64data = base64.b64encode(data).decode('ascii')
                message = {'cmd': 'sync', 'data': b64data, 'id': stream.id}
                while not self.tunnel.dispatch(message):
                    # If the dispatch fails, we have to wait before retry.
                    yield from asyncio.sleep(1.0)
                    assert self.running, 'aborting stream #{}'.format(stream.id)

            # Closing socks5 client connection
            self.logger.debug('closing stream #{}'.format(stream.id))
            # We have to control if the writer was not closed by a "disconnect" message first.
            if stream.status == 0:
                try:
                    yield from writer.drain()
                except BrokenPipeError:
                    pass
                except ConnectionResetError:
                    pass

        except AssertionError as e:
            self.logger.debug(e.args[0])

        except asyncio.IncompleteReadError:
            self.logger.debug('incomplete read')

        except KeyboardInterrupt:
            self.loop.stop()

        except RuntimeError:
            self.logger.critical('adapter exception: \n{}'.format(traceback.format_exc()))

        if stream.id in self.streams:
            del self.streams[stream.id]

    @asyncio.coroutine
    def execute(self, message):
        try:
            self.logger.debug('executing message {}'.format(message))
            with (yield from self.lock):
                if message['cmd'] == 'status':
                    if message['id'] in self.streams:
                        yield from self.streams[message['id']].set_status(message['value'])
                        self.lock.notify_all()

                elif message['cmd'] == 'sync':
                    if message['id'] in self.streams:
                        data = base64.b64decode(message['data'].encode('ascii'))
                        self.streams[message['id']].writer.write(data)

                elif message['cmd'] == 'stop':
                    self.loop.stop()
        except KeyboardInterrupt:
            self.loop.stop()

    def dispatch(self, message):
        def async_execute(msg):
            asyncio.async(self.execute(msg), loop=self.loop)
        self.loop.call_soon_threadsafe(async_execute, message)

    @asyncio.coroutine
    def stop_and_wait(self):
        self.server.close()
        yield from self.server.wait_closed()
        with (yield from self.lock):
            self.running = False
            self.lock.notify_all()

        while self.streams.values():
            _, stream = self.streams.popitem()
            stream.writer.close()
            try:
                yield from stream.task
            except:
                pass

    def stop(self):
        if self.running:
            self.loop.run_until_complete(self.stop_and_wait())

    def start(self, loop):
        self.loop = loop
        self.running = True
        handler = asyncio.start_server(self.new_connection, self.address, self.port, loop=loop)
        self.server = loop.run_until_complete(handler)
        self.logger.info('listening on {}:{}'.format(self.address, self.port))
