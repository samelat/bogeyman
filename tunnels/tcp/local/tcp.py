
import json
import time
import struct
import asyncio
import logging


class TCP:

    def __init__(self, tunnel_ip, tunnel_port, reverse=False):
        self.logger = logging.getLogger('bogeyman')
        self.host = tunnel_ip
        self.port = tunnel_port
        self.reverse = reverse

        self.task = None
        self.tunnel = None
        self.adapter = None
        self.loop = None
        self.writer = None
        self.running = False

    def set_peer(self, peer):
        self.adapter = peer

    def dispatch(self, message):
        if self.writer is None:
            return False
        self.logger.debug('receive message {}'.format(message))
        data = json.dumps(message).encode()
        self.writer.write(struct.pack('>H', len(data)) + data)
        return True

    @asyncio.coroutine
    def handler(self, reader, writer):
        self.logger.info('connection ready')
        self.task = asyncio.Task.current_task(loop=self.loop)

        self.writer = writer
        while self.running:
            try:
                data = yield from reader.readexactly(2)
                size = struct.unpack('>H', data)[0]
                data = yield from reader.readexactly(size)

            except asyncio.streams.IncompleteReadError:
                self.writer = None
                self.logger.info('disconnected')
                break

            except asyncio.CancelledError:
                break

            except KeyboardInterrupt:
                self.loop.stop()
                break

            message = json.loads(data.decode('ascii'))

            self.logger.debug('incoming message {}'.format(message))
            self.adapter.dispatch(message)

        try:
            self.writer.close()
        except:
            pass
        self.logger.info('connection closed')

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
            self.logger.debug('timeout')
        except asyncio.CancelledError:
            self.logger.debug('cancelled')
        except:
            self.logger.debug('unknown exception')

        self.task.cancel()
        yield from self.task

        #if self.task is not None:
        #    print('ESPERANDO TASK QUE ESTA A MEDIAS')
        #    yield from self.task

    def stop(self):
        self.loop.run_until_complete(self.wait())

    def start(self, loop):
        self.loop = loop
        self.running = True

        if self.reverse:
            server_coroutine = asyncio.start_server(self.handler, self.host, self.port, loop=loop)
            self.tunnel = loop.run_until_complete(server_coroutine)
            self.logger.info('listening on {}:{}'.format(self.host, self.port))

        else:
            self.tunnel = asyncio.async(self.connect(), loop=loop)
