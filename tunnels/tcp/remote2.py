#!/usr/bin/python

import time
import json
import base64
import socket
import select
import struct
import logging
import argparse
import traceback
import ConfigParser as configparser

from threading import Thread, Condition


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

        # Stage 2 - trying to reconnect tunnel
        # Stage 1 - tunnel working
        # Stage 0 - aborting
        self.stage = 2
        self.lock = Condition()
        self.streams = {}
        self.streams_thread = None
        self.connecting_streams = []

    # Sends message back to the other tunnel extreme.
    def dispatch(self, message):
        data = json.dumps(message).encode()
        data = struct.pack('>H', len(data)) + data
        while data:
            with self.lock:
                # if the tunnel is not connected
                while self.stage == 2:
                    self.lock.wait()
                if self.stage == 0:
                    return False
            try:
                sent_bytes = self.sock.send(data)
                data = data[sent_bytes:]
            except Exception as e:
                logging.debug('[#{}] sending exception: {}'.format(message['id'], e))
                continue
        return True

    def streams_handler(self):
        error_to_status = {111: 5, 0: 0}
        while True:
            with self.lock:
                if self.stage == 0:
                    return

                if not (self.streams or self.connecting_streams):
                    self.lock.wait()
                    continue

                active_streams = list(self.streams.values())
                connecting_streams = list(self.connecting_streams)

            ready_streams, connected_streams, _ = select.select(active_streams, connecting_streams, [], 1.0)

            # Controls the connections' result value
            for stream in connected_streams:
                error = stream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                # 4 is the default status
                status = error_to_status.get(error, 4)

                if not self.dispatch({'cmd': 'status', 'value': status, 'id': stream.sid}):
                    return

                if status == 0:
                    with self.lock:
                        self.streams[stream.sid] = stream
                        self.lock.notify_all()
                    logging.info('connection #{} done'.format(stream.sid))
                else:
                    stream.close()

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
                        logging.debug('[#{}] connection timeout'.format(stream.sid))
                        stream.close()

            for stream in ready_streams:
                try:
                    data = stream.recv(48750)
                    if data:
                        logging.debug('data read: {}'.format(repr(data)))
                        if not self.dispatch({'cmd': 'sync', 'data': base64.b64encode(data), 'id': stream.sid}):
                            return
                        continue

                except socket.error as e:
                    logging.debug('connection #{} error: {}'.format(stream.sid, e))

                self.dispatch({'id': stream.sid, 'cmd': 'disconnect'})
                with self.lock:
                    stream.close()
                    del(self.streams[stream.sid])

    def fixed_recv(self, size):
        total_data = b''
        while len(total_data) < size:
            data = self.sock.recv(size - len(total_data))
            if not data:
                return None
            total_data += data
        return total_data

    def tunnel_handler(self):
        logging.info('connected')

        # Handles each incoming message
        while True:
            with self.lock:
                if self.stage == 0:
                    break

            # Reads message size
            data = self.fixed_recv(2)
            if data is None:
                break
            size = struct.unpack('>H', data)[0]

            # Reads message
            data = self.fixed_recv(size)
            if data is None:
                break

            message = json.loads(data)
            logging.debug('new message {}'.format(message))

            if message['cmd'] == 'connect':
                stream = Stream(message['id'])
                stream.setblocking(0)
                stream.connect_ex((message['addr'], message['port']))
                logging.info('waiting connection #{id} to {addr}:{port}'.format(**message))
                with self.lock:
                    self.connecting_streams.append(stream)
                    self.lock.notify_all()

            elif message['cmd'] == 'sync':
                data = base64.b64decode(message['data'])
                with self.lock:
                    if message['id'] in self.streams:
                        self.streams[message['id']].send(data)

            elif message['cmd'] == 'stop':
                with self.lock:
                    self.stage = 0
                    self.lock.notify_all()

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
            while True:
                with self.lock:
                    if self.stage == 0:
                        break

                try:
                    if reverse:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        logging.info('connecting to {}:{}'.format(self.host, self.port))
                        sock.connect((self.host, self.port))

                    else:
                        sock, address = main_sock.accept()
                        logging.info('connection from {}:{}'.format(*address))

                    self.sock = sock
                    with self.lock:
                        self.stage = 1
                        self.lock.notify_all()
                    self.tunnel_handler()

                    logging.info('connection closed')

                except socket.timeout:
                    logging.info('connection timeout')

                except socket.error:
                    logging.info('connection refused')

                with self.lock:
                    self.stage = 2
                    self.lock.notify_all()

                if reverse:
                    logging.debug('waiting 4 seconds before retrying reconnection')
                    time.sleep(4.0)

        except KeyboardInterrupt:
            logging.info('please wait until the program stops...')

        except:
            logging.critical('tunnel exception: \n{}'.format(traceback.format_exc()))

        with self.lock:
            self.stage = 0
            self.lock.notify_all()

        if main_sock is not None:
            main_sock.close()

        self.streams_thread.join(2.0)

        logging.debug('shutting down')


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
    logging.basicConfig(level=getattr(logging, config['log'].upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    tunnel = Tunnel(config['ip'], config['port'])
    tunnel.start(config['reverse'])
