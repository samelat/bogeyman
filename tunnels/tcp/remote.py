
import sys
import json
import struct
import base64
import asyncio
import argparse


class Stream(asyncio.Protocol):
    def __init__(self, sid, tunnel):
        self.sid = sid
        self.tunnel = tunnel
        self.transport = None
        print('[!] Connecting')

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        # print('Data received: {}'.format(data))
        # sys.stdout.flush()
        remaining = data
        while remaining:
            b64data = base64.b64encode(remaining[:48750]).decode('ascii')
            remaining = remaining[48750:]
            self.tunnel.dispatch({'cmd': 'sync', 'data': b64data, 'id': self.sid})

    def connection_lost(self, exc):
        self.tunnel.dispatch({'cmd': 'disconnect', 'id': self.sid})
        print('The server closed the connection')
        print('Stop the event loop')

    @asyncio.coroutine
    def connect(self, address, port):
        try:
            yield from self.tunnel.loop.create_connection(lambda: self, address, port)
            self.tunnel.streams[self.sid] = self
            self.tunnel.dispatch({'cmd': 'status', 'value': 0, 'id': self.sid})

        except Exception as e:
            print(e)
            print('[!] Connection refused: {}:{}'.format(address, port))
            self.tunnel.dispatch({'cmd': 'status', 'value': 5, 'id': self.sid})


class Tunnel:

    def __init__(self, address, port):
        self.address = address
        self.port = port
        self.loop = None
        self.writer = None
        self.streams = {}

    # Send message back to the other tunnel extreme.
    def dispatch(self, message):
        data = json.dumps(message).encode()
        self.writer.write(struct.pack('>H', len(data)) + data)

    @asyncio.coroutine
    def handle(self, reader, writer):
        self.writer = writer

        while True:
            data = yield from reader.readexactly(2)
            size = struct.unpack('>H', data)[0]
            data = yield from reader.readexactly(size)
            message = json.loads(data.decode('ascii'))
            print('[!] New message: {}'.format(message))

            if message['cmd'] == 'connect':
                stream = Stream(message['id'], self)
                try:
                    print('[!] Trying to connect to {addr}:{port}'.format(**message))
                    # yield from self.loop.create_connection(lambda: stream, message['addr'], message['port'])
                    asyncio.async(stream.connect(message['addr'], message['port']), loop=self.loop)
                    print('[!] Connection done')

                except Exception as e:
                    print(e)
                    print('[!] Connection refused: {addr}:{port}'.format(**message))
                    self.dispatch({'cmd': 'status', 'value': 5, 'id': message['id']})

            elif message['cmd'] == 'sync':
                data = base64.b64decode(message['data'].encode('ascii'))
                self.streams[message['id']].transport.write(data)

    # Connects with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while True:
            # try:
            reader, writer = yield from asyncio.open_connection(self.address, self.port, loop=self.loop)
            yield from self.handle(reader, writer)

            # except Exception:
            #     print('[!] Tunnel connection exception')
            #     # It waits 1 second before try again.
            #     yield from asyncio.sleep(1)

    def start(self, reverse):
        self.loop = asyncio.get_event_loop()

        if reverse:
            # try:
            self.loop.run_until_complete(self.connect())

            # except Exception:
            #     print('CCCCCCCCCCCCCCCCCCCCCCC')

        else:
            '''
            handler = asyncio.start_server(self.new_connection, self.hostname, self.port, loop=loop)
            server = loop.run_until_complete(handler)

            coro = asyncio.start_server(handle_echo, '127.0.0.1', 8888, loop=loop)
            server = self.loop.run_until_complete(coro)

            # Serve requests until Ctrl+C is pressed
            print('Serving on {}'.format(server.sockets[0].getsockname()))
            try:
                loop.run_forever()
            except KeyboardInterrupt:
                pass

            # Close the server
            server.close()
            loop.run_until_complete(server.wait_closed())
            '''

        print('[!] CLOSE')
        self.loop.close()

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=8888,
                        help='Host port')

    parser.add_argument('-a', '--addr', default='127.0.0.1',
                        help='Host address')

    parser.add_argument('-r', '--reverse', action='store_true',
                        help='Use reverse connection.')

    args = parser.parse_args()

    tunnel = Tunnel(args.addr, args.port)
    tunnel.start(args.reverse)
