#!/usr/bin/python3

import json
import struct
import base64
import asyncio
import logging
import argparse
import traceback
import configparser


class Stream(asyncio.Protocol):
    def __init__(self, sid, tunnel):
        self.sid = sid
        self.tunnel = tunnel
        self.logger = tunnel.logger
        self.transport = None
        self.task = None

    def connection_made(self, transport):
        self.logger.info('Stream #{} connected'.format(self.sid))
        self.transport = transport
        self.task = None

    def data_received(self, data):
        remaining = data
        while remaining:
            b64data = base64.b64encode(remaining[:48750]).decode('ascii')
            remaining = remaining[48750:]
            self.tunnel.dispatch({'cmd': 'sync', 'data': b64data, 'id': self.sid})

    def connection_lost(self, exc):
        self.logger.info('Closing stream connection #{}'.format(self.sid))
        # self.tunnel.dispatch({'cmd': 'disconnect', 'id': self.sid})

    @asyncio.coroutine
    def connect(self, address, port):
        try:
            self.logger.info('Stream #{} trying to connect to {}:{}'.format(self.sid, address, port))
            yield from self.tunnel.loop.create_connection(lambda: self, address, port)
            status = 0

        except TimeoutError:
            self.logger.debug('Connection timeout')
            status = 6
        except ConnectionRefusedError:
            self.logger.debug('Connection refused')
            status = 5
        except asyncio.CancelledError:
            return
        except GeneratorExit:
            return
        except KeyboardInterrupt:
            self.tunnel.loop.stop()
            return
        except BaseException:
            self.logger.critical('unknown connection error: \n{}'.format(traceback.format_exc()))
            status = 4

        self.tunnel.dispatch({'cmd': 'status', 'value': status, 'id': self.sid})

        if status != 0:
            del self.tunnel.streams[self.sid]


class Tunnel:

    def __init__(self, host, port, logger):
        self.host = host
        self.port = port
        self.logger = logger
        self.loop = None
        self.tunnel = None
        self.writer = None
        self.streams = {}
        self.running = False
        self.pending_tasks = []

    # Send message back to the other tunnel extreme.
    def dispatch(self, message):
        if not self.running:
            return
        data = json.dumps(message).encode()
        self.logger.debug('outgoing message: {}'.format(message))
        self.writer.write(struct.pack('>H', len(data)) + data)

    @asyncio.coroutine
    def handler(self, reader, writer):
        self.writer = writer
        self.logger.info('connection ready')
        # Handles each incoming message

        while self.running:
            try:
                data = yield from reader.readexactly(2)
                size = struct.unpack('>H', data)[0]
                data = yield from reader.readexactly(size)
                message = json.loads(data.decode('ascii'))
                self.logger.debug('incoming message: {}'.format(message))

                if message['cmd'] == 'connect':
                    stream = Stream(message['id'], self)
                    self.streams[stream.sid] = stream
                    stream.task = asyncio.async(stream.connect(message['addr'], message['port']), loop=self.loop)
                    # task = asyncio.async(stream.connect(message['addr'], message['port']), loop=self.loop)
                    # self.pending_tasks.append(task)

                elif message['cmd'] == 'sync':
                    if message['id'] not in self.streams:
                        self.dispatch({'cmd': 'status', 'value': 5, 'id': message['id']})
                        continue
                    data = base64.b64decode(message['data'].encode('ascii'))
                    self.streams[message['id']].transport.write(data)

                # self.pending_tasks = [task for task in self.pending_tasks if not task.done()]

            except asyncio.IncompleteReadError:
                self.logger.debug('tunnel connection lost')
                return

            except KeyboardInterrupt:
                self.loop.stop()
                return

    # Keeps connecting with the other tunnel extreme.
    @asyncio.coroutine
    def connect(self):
        while self.running:
            self.logger.info('connecting to {}:{}'.format(self.host, self.port))
            try:
                connect_coro = asyncio.open_connection(self.host, self.port, loop=self.loop)
                reader, writer = yield from asyncio.wait_for(connect_coro, 8.0)
                yield from self.handler(reader, writer)

            except asyncio.TimeoutError:
                self.logger.info('connection timeout')

            except ConnectionRefusedError:
                self.logger.info('connection refused')
                yield from asyncio.sleep(8.0)

            except KeyboardInterrupt:
                self.loop.stop()
                self.logger.debug('execution aborted')
                break

            except asyncio.CancelledError:
                break

            except:
                self.logger.error('unknown tunnel exception: \n{}'.format(traceback.format_exc()))
                break

    @asyncio.coroutine
    def stop_and_wait(self):
        # First we have to stop the tunnel connection.
        self.running = False
        try:
            self.writer.close()
            if True:
                self.tunnel.cancel()
                yield from self.tunnel
            else:
                self.tunnel.close()
                yield from asyncio.wait_for(self.tunnel.wait_closed(), 2.0, loop=self.loop)
        except:
            pass

        # Then, we start stopping the streams
        for stream in self.streams.values():
            try:
                if stream.task is None:
                    stream.transport.close()
                else:
                    stream.task.cancel()
                    yield from stream.task
            except:
                pass

    def start(self, reverse):
        self.loop = asyncio.get_event_loop()

        try:
            self.running = True
            if reverse:
                # self.loop.run_until_complete(self.connect())
                self.tunnel = asyncio.async(self.connect(), loop=self.loop)

            else:
                server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=self.loop)
                self.tunnel = self.loop.run_until_complete(server_coroutine)
                self.logger.info('listening on {}:{}'.format(self.host, self.port))

            self.loop.run_forever()
        except KeyboardInterrupt:
            self.logger.info('stopping tunnel')

        self.loop.run_until_complete(self.stop_and_wait())

        self.logger.debug('closing loop')
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
    config = {'ip': '127.0.0.1', 'port': 8888, 'log': 'info', 'reverse': False}

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
    logging.basicConfig(format='[%(levelname)-0.1s][%(module)s] %(message)s')
    logger = logging.getLogger('remote3')
    logger.setLevel(getattr(logging, config['log'].upper()))

    tunnel = Tunnel(config['ip'], config['port'], logger)
    tunnel.start(args.reverse)
