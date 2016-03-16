#!/usr/bin/python

import time
import json
import base64
import socket
import select
import struct
import logging
import argparse

from threading import Thread, Lock


class Stream(socket.socket):
    def __init__(self, sid):
        socket.socket.__init__(self, socket.AF_INET, socket.SOCK_STREAM)
        self.sid = sid
        self.creation = time.time()


class Tunnel:

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None

        self.running = True
        self.lock = Lock()
        self.streams = {}
        self.streams_thread = None
        self.connecting_streams = []

    # Send message back to the other tunnel extreme.
    def dispatch(self, message):
        data = json.dumps(message).encode()
        self.sock.send(struct.pack('>H', len(data)) + data)

    def streams_handler(self):

        error_to_status = {111: 5, 0: 0}
        while self.running:
            with self.lock:
                active_streams = list(self.streams.values())
                connecting_streams = list(self.connecting_streams)

            ready_streams, connected_streams, _ = select.select(active_streams, connecting_streams, [], 1.0)

            # Controls the connections' result value
            for stream in connected_streams:
                error = stream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                # 4 is the default status
                status = error_to_status.get(error, 4)
                if status == 0:
                    with self.lock:
                        self.streams[stream.sid] = stream
                else:
                    stream.close()
                self.dispatch({'cmd': 'status', 'value': status, 'id': stream.sid})

            processed_sids = set([stream.sid for stream in connected_streams])
            current_time = time.time()
            with self.lock:
                not_ready_streams = [stream for stream in self.connecting_streams if stream.sid not in processed_sids]
                # Controls which connections have achieved timeout
                self.connecting_streams = []
                for stream in not_ready_streams:
                    if (current_time - stream.creation) < 8.0:
                        self.connecting_streams.append(stream)
                    else:
                        stream.close()

            for stream in ready_streams:
                try:
                    data = stream.recv(48750)
                    if data:
                        logging.debug('data read: {}'.format(repr(data)))
                        self.dispatch({'cmd': 'sync', 'data': base64.b64encode(data), 'id': stream.sid})
                        continue

                except socket.error as e:
                    logging.debug('connection #{} error: {}'.format(stream.sid, e))

                self.dispatch({'id': stream.sid, 'cmd': 'disconnect'})
                with self.lock:
                    stream.close()
                    del(self.streams[stream.sid])

    def tunnel_handler(self):
        logging.info('connected')

        # Handles each incoming message
        while self.running:
            data = self.sock.recv(2, socket.MSG_WAITALL)
            if len(data) < 2:
                break

            size = struct.unpack('>H', data)[0]
            data = self.sock.recv(size, socket.MSG_WAITALL)
            if len(data) < size:
                break

            message = json.loads(data)
            logging.debug('new message {}'.format(message))

            if message['cmd'] == 'connect':
                stream = Stream(message['id'])
                stream.setblocking(0)
                stream.connect_ex((message['addr'], message['port']))
                with self.lock:
                    self.connecting_streams.append(stream)

            elif message['cmd'] == 'sync':
                data = base64.b64decode(message['data'])
                with self.lock:
                    if message['id'] in self.streams:
                        self.streams[message['id']].send(data)

            elif message['cmd'] == 'stop':
                with self.lock:
                    self.running = False

    # Keeps connecting with the other tunnel extreme.
    def start(self, reverse):
        main_sock = None
        try:
            # Starts streams handler thread.
            self.streams_thread = Thread(target=self.streams_handler)
            self.streams_thread.start()

            # Starts server socket if we have to listen for connections.
            if not reverse:
                main_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                main_sock.bind((self.host, self.port))
                main_sock.listen(2)
                logging.info('listening on {}:{}'.format(self.host, self.port))

            # Reconnects until KeyboardInterrupt occur.
            while self.running:
                try:
                    if reverse:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        logging.info('connecting to {}:{}'.format(self.host, self.port))
                        sock.connect((self.host, self.port))

                    else:
                        sock, address = main_sock.accept()
                        logging.info('connection from {}:{}'.format(*address))

                    self.sock = sock
                    self.tunnel_handler()

                    logging.info('connection closed')

                except socket.timeout:
                    logging.info('connection timeout')

                except socket.error:
                    logging.info('connection refused')
                    time.sleep(8.0)

        except KeyboardInterrupt:
            logging.info('please wait until the program stops...')

        except Exception as e:
            logging.error('tunnel exception: {}'.format(e))

        if main_sock is not None:
            main_sock.close()

        with self.lock:
            self.running = False
        self.streams_thread.join(2.0)

        logging.debug('shutting down')


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=8888,
                        help='host port. default 8888')

    parser.add_argument('-i', '--host', default='127.0.0.1',
                        help='host address. default 127.0.0.1')

    parser.add_argument('-r', '--reverse', action='store_true',
                        help='use reverse connection')

    parser.add_argument('-l', '--log', default='info',
                        choices=['debug', 'info', 'warning', 'error', 'critical'])

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log.upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    tunnel = Tunnel(args.host, args.port)
    tunnel.start(args.reverse)
