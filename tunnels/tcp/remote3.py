
import json
import struct
import base64
import asyncio
import logging
import argparse


class Stream(asyncio.Protocol):
    def __init__(self, sid, tunnel):
        self.sid = sid
        self.tunnel = tunnel
        self.transport = None

    def connection_made(self, transport):
        logging.info('Stream #{} connected'.format(self.sid))
        self.transport = transport

    def data_received(self, data):
        remaining = data
        while remaining:
            b64data = base64.b64encode(remaining[:48750]).decode('ascii')
            remaining = remaining[48750:]
            self.tunnel.dispatch({'cmd': 'sync', 'data': b64data, 'id': self.sid})

    def connection_lost(self, exc):
        logging.info('Closing stream connection #{}'.format(self.sid))
        self.tunnel.dispatch({'cmd': 'disconnect', 'id': self.sid})

    @asyncio.coroutine
    def connect(self, address, port):
        try:
            logging.info('Stream #{} trying to connect to {}:{}'.format(self.sid, address, port))
            yield from self.tunnel.loop.create_connection(lambda: self, address, port)
            status = 0

        except TimeoutError:
            logging.debug('Connection timeout')
            status = 6
        except ConnectionRefusedError:
            logging.debug('Connection refused')
            status = 5
        except Exception as e:
            logging.debug('Unknown connection error: {}'.format(e))
            status = 4

        if status == 0:
            self.tunnel.streams[self.sid] = self
        self.tunnel.dispatch({'cmd': 'status', 'value': status, 'id': self.sid})


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
    def handler(self, reader, writer):
        self.writer = writer
        # Handles each incoming message
        while True:
            data = yield from reader.readexactly(2)
            size = struct.unpack('>H', data)[0]
            data = yield from reader.readexactly(size)
            message = json.loads(data.decode('ascii'))
            logging.debug('New message: {}'.format(message))

            if message['cmd'] == 'connect':
                stream = Stream(message['id'], self)
                asyncio.async(stream.connect(message['addr'], message['port']), loop=self.loop)

            elif message['cmd'] == 'sync':
                data = base64.b64decode(message['data'].encode('ascii'))
                self.streams[message['id']].transport.write(data)

    # Keeps connecting with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while True:
            reader, writer = yield from asyncio.open_connection(self.address, self.port, loop=self.loop)
            yield from self.handler(reader, writer)

    def start(self, reverse):
        self.loop = asyncio.get_event_loop()

        try:
            if reverse:
                self.loop.run_until_complete(self.connect())

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
        except KeyboardInterrupt:
            pass

        logging.debug('Closing loop')
        self.loop.close()

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=8888,
                        help='host port. default 8888')

    parser.add_argument('-a', '--host', default='127.0.0.1',
                        help='host address. default 127.0.0.1')

    parser.add_argument('-r', '--reverse', action='store_true',
                        help='use reverse connection')

    parser.add_argument('-l', '--log', default='notset',
                        choices=['debug', 'info', 'warning', 'error', 'critical'])

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log.upper()),
                        format='[%(levelname)-0.1s] %(message)s')

    tunnel = Tunnel(args.host, args.port)
    tunnel.start(args.reverse)
