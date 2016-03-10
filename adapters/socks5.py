
import base64
import struct
import random
import socket
import asyncio


class Socks5:

    def __init__(self, address, port):
        self.address = address
        self.port = port
        self.tunnel = None

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
        print('[!] Connection #{} from: {}:{}'.format(cid, *src_info))

        # Start Socks5 protocol implementation
        data = yield from reader.readexactly(2)
        version, nmethods = struct.unpack('BB', data)
        print('[!] Socks version: {} - Number of methods: {}'.format(version, nmethods))

        if version not in [4, 5] or nmethods < 1:
            print('[e] Incorrect header information')
            writer.close()
            return

        data = yield from reader.readexactly(nmethods)
        methods = list(data)
        print('[!] Suggested auth methods: {}'.format(methods))
        # For now we only accept non-authentication.
        if 0 not in methods:
            print('[e] Authentication methods not supported')
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
            print('[e] Authentication methods not supported')
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
            print(domain_size)
            data = yield from reader.readexactly(domain_size + 2)
            address = data[:domain_size].decode('ascii')
            port = struct.unpack('>H', data[domain_size:])[0]

        # We will implement ipv6 when we need it :P.

        print('[!] Trying to connect to {}:{}'.format(address, port))
        with (yield from self.lock):
            self.streams[cid] = {'writer': writer, 'status': -1}

        # Once we know where the client wants to connect to, we send the command to the tunnel.
        self.tunnel.dispatch({'cmd': 'connect', 'addr': address, 'port': port, 'id': cid})

        # and we wait for the connection's result ...
        with (yield from self.lock):
            while self.streams[cid]['status'] is -1:
                print('[!] Waiting until stream status change')
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
            data = yield from reader.read(8192)
            print('[!] Received data: {}'.format(repr(data)))
            if not data:
                break

            b64data = base64.b64encode(data).decode('ascii')
            message = {'cmd': 'sync', 'data': b64data, 'id': cid}
            self.tunnel.dispatch(message)

        print('[!] Closing connection #{0}'.format(cid))
        with (yield from self.lock):
            # We have to control if the writer was not closed by a "disconnect" message first.
            if self.streams[cid]['status'] == 0:
                yield from writer.drain()
                writer.close()
            del(self.streams[cid])

    @asyncio.coroutine
    def execute(self, message):
        print('[!] Executing message {}'.format(message))
        with (yield from self.lock):
            if message['cmd'] == 'status':
                self.streams[message['id']]['status'] = message['value']
                self.lock.notify_all()

            elif message['cmd'] == 'disconnect':
                if message['id'] in self.streams:
                    yield from self.streams[message['id']]['writer'].drain()
                    self.streams[message['id']]['writer'].close()
                    self.streams[message['id']]['status'] = -2
                    self.lock.notify_all()
                print('[!] #{} Disconnected'.format(message['id']))

            elif message['cmd'] == 'sync':
                data = base64.b64decode(message['data'].encode('ascii'))
                self.streams[message['id']]['writer'].write(data)

    def dispatch(self, message):
        def async_execute(msg):
            asyncio.async(self.execute(msg), loop=self.loop)
        self.loop.call_soon_threadsafe(async_execute, message)

    def start(self, loop):
        self.loop = loop
        handler = asyncio.start_server(self.new_connection, self.address, self.port, loop=loop)
        server = loop.run_until_complete(handler)
        print('[!] Socks5 listening on {}'.format(server.sockets[0].getsockname()))
        return server


