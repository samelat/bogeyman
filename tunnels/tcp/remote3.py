#!/usr/bin/python3

import json
import struct
import base64
import asyncio
import logging
import argparse
import configparser


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

    def __init__(self, host, port):
        self.host = host
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
            logging.debug('new message {}'.format(message))

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
            logging.info('connecting to {}:{}'.format(self.host, self.port))
            try:
                connect_coro = asyncio.open_connection(self.host, self.port, loop=self.loop)
                reader, writer = yield from asyncio.wait_for(connect_coro, 8.0)
                yield from self.handler(reader, writer)

            except asyncio.TimeoutError:
                logging.info('connection timeout')

            except ConnectionRefusedError:
                logging.info('connection refused')
                yield from asyncio.sleep(8.0)

            except Exception as e:
                logging.error('unknown tunnel exception: {}'.format(e))
                break

    def start(self, reverse):
        self.loop = asyncio.get_event_loop()

        try:
            if reverse:
                self.loop.run_until_complete(self.connect())

            else:
                server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=self.loop)
                self.loop.run_until_complete(server_coroutine)
                logging.info('listening on {}:{}'.format(self.host, self.port))
                self.loop.run_forever()
        except KeyboardInterrupt:
            pass

        logging.debug('closing loop')
        self.loop.close()

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, help='host port (default: 8888)')
    parser.add_argument('-i', '--ip', help='host address. default 127.0.0.1')
    parser.add_argument('-r', '--reverse', action='store_true', help='use reverse connection')
    parser.add_argument('-l', '--log', choices=['debug', 'info', 'warning', 'error', 'critical'])
    parser.add_argument('-c', '--config', default='', help='uses a configuration file')

    args = parser.parse_args()

    # Default configuration
    config = {'ip': '127.0.0.1', 'port': 1080, 'log': 'info', 'reverse': False}

    # Config file configuration
    if args.config:
        config_file = configparser.ConfigParser(allow_no_value=True)
        if config_file.read(args.config) and ('tcp' in config_file.sections()):
            # Tunnel configuration
            for key, value in config_file.items('tcp'):
                config[key.lower()] = value if value is None else value.lower()

    for option in ['ip', 'port', 'reverse', 'log']:
        value = getattr(args, option)
        config[option] = value if value else config[option]

    # Starts program
    logging.basicConfig(level=getattr(logging, config['log'].upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    tunnel = Tunnel(args.host, args.port)
    tunnel.start(args.reverse)
