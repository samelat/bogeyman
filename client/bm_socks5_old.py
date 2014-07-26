#!/usr/bin/python

'''
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.
 
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
 
   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>
 
   Author: Gaston Traberg <samelat@gmail.com>
'''

# I am importing this module just to fix the SSL problem
import ssl

import re
import sys
import time
import select
import socket
import urllib
import urllib2
import argparse

from struct import unpack, pack

from threading import Lock
from threading import Thread
from threading import Semaphore

'''
* Comandos Request
*    00    - data refresh          - <stream_id>|<outgoing_data>
*                         Response - <response_code>|<incomming_data>
*
*    01    - close socket          - <stream_id>
*                         Response - <response_code>
*
*    02    - create tcp stream     - <hostname><port>
*                         Response - <response_code>
*
*    99    - Halt server           -
*                         Response - 00
* 
* Response codes
*    00    - OK
*    01    - Connection Refused
*    02    - Connection Closed
*
*    50    - Malformed request
*    51    - Unknown command
*    52    - Unknown parameter
'''
class HTTPSocks5Adapter:

    # Socket layer errors
    SUCCESS            = 0
    CONNECTION_REFUSED = 1
    CONNECTION_CLOSED  = 2
    UNKNOWN_HOST_NAME  = 3

    # Adapter errors
    HTTP_REQUEST_FAIL  = 20

    # Protocol errors
    MALFORMED_REQUEST  = 50
    UNKNOWN_COMMAND    = 51
    UNKNOWN_PARAMETER  = 52

    # Internal server protocol errors
    CLIENT_READY       = 90
    SERVER_BUSY        = 91

    END_SERVICE        = 99

    def __init__(self, http_host, requests_sem):
        self.http_host = http_host
        self.requests_sem = requests_sem

        self.incomming_data = []
        self.outgoing_data  = []

        self.stream_id = None

        self._delay = 0

        self.hostname = None
        self.hostport = None

    @staticmethod
    def check_service(http_host):
        try:
            response = urllib2.urlopen(http_host)
        except urllib2.HTTPError as e:
            return False

        if response.read() == '|90':
            return True
        return False

    @staticmethod
    def begin_service(http_host):
        try:
            response = urllib2.urlopen(http_host + '?server', timeout=4)
        except socket.timeout:
            return True
        except ssl.SSLError:
			return True
        except urllib2.HTTPError as e:
            return False

        return False

    @staticmethod
    def end_service(http_host):

        request = urllib2.Request(http_host, 'data=|{0}'.format(HTTPSocks5Adapter.END_SERVICE))

        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError as e:
            return False

        if response.read() == '|00':
            return True
        return False


    def connect(self, host, port):

        if self.stream_id:
            return -1

        self.hostname = host
        self.hostport = port

        request = urllib2.Request(self.http_host, 'data=|02|{0}:{1}'.format(host, port))

        self.requests_sem.acquire()
        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError as e:
            return self.HTTP_REQUEST_FAIL
        finally:
            self.requests_sem.release()

        data = response.read()

        response = data.split('|')

        response_code = int(response[1])

        # TODO: ERROR HANDLING
        if response_code == self.SUCCESS:
            self.stream_id = response[2]
        else:
            return response_code

        return self.SUCCESS


    def _update_data(self):

        request = 'data=|00|{0}'.format(self.stream_id)
        if self.outgoing_data:
            data = urllib.quote(self.outgoing_data.pop(0).encode('base64'))
            request += '|{0}'.format(data)

        request = urllib2.Request(self.http_host, request)

        self.requests_sem.acquire()
        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError as e:
            self.stream_id = None
            return False
        finally:
            self.requests_sem.release()

        data = response.read()

        response = data.split('|')

        response_code = int(response[1])

        # TODO: ERROR HANDLING
        if response_code == self.SUCCESS:
            if len(response) > 2:
                self._delay = 0
                data = response[2].decode('base64')
                self.incomming_data.append(data)
        
        elif response_code == self.CONNECTION_CLOSED:
            self.stream_id = None
            self._delay = 0

        elif response_code == self.SERVER_BUSY:
            self._delay += 1
            # print '[!] Server too busy. Waiting {0} secs.'.format(self._delay)
            time.sleep(self._delay)
            return True
        else:
            self.stream_id = None

        return False


    def recv(self, size):

        if self.stream_id:
            while self._update_data():
                time.sleep(self._delay)

        elif not self.incomming_data:
            return None

        data = ''
        if self.incomming_data:
            data = self.incomming_data.pop(0)

        return data


    def send(self, data):

        if not self.stream_id:
            return bool(self.incomming_data)

        if data:
            self.outgoing_data.append(data)
            self._delay = 0

        return True


    def close(self):

        while self.outgoing_data and self.stream_id:
            while self._update_data():
                continue

        if not self.stream_id:
            return

        request = urllib2.Request(self.http_host, 'data=|01|{0}'.format(self.stream_id))

        self.requests_sem.acquire()
        response = urllib2.urlopen(request)
        self.requests_sem.release()


class Socks5Stream(Thread):

    NO_AUTH = 0

    CMD_CONNECT = 1
    CMD_BIND    = 2
    CMD_UDP     = 3

    ADDR_V4     = 1
    ADDR_DNAME  = 3


    def __init__(self, sock, requests_sem, status_bar, server_uri):
        Thread.__init__(self)
        self.socket = sock;
        self.remote_host = HTTPSocks5Adapter(server_uri, requests_sem)
        self.server_uri = server_uri
        self.status_bar = status_bar

        self._continue = True


    def _handshake(self):

        # Authentication handler
        auth_packet = self.socket.recv(256)

        packet = []
        for byte in auth_packet:
            packet.append(unpack('B', byte)[0])

        if self.NO_AUTH in packet[2:]:
            self.socket.send(pack('B', packet[0]) + '\x00')
        else:
            self.socket.send(pack('B', packet[0]) + '\xff')
            return

        # Request Handler
        command_packet = self.socket.recv(256)

        version, command, _, addr_type = unpack('BBBB', command_packet[:4])

        raw_addr = None
        port = None

        hostname = None

        if addr_type == self.ADDR_V4:
            port = unpack('>H', command_packet[8:10])[0]
            raw_addr = command_packet[4:8]
            hostname = socket.inet_ntoa(raw_addr)

        elif addr_type == self.ADDR_DNAME:
            hostname_size = unpack('B', command_packet[4])[0]
            raw_addr = command_packet[4:5+hostname_size]
            hostname = raw_addr[1:]
            port = unpack('>H', command_packet[5+hostname_size:7+hostname_size])[0]

        else:
            # ?
            return

        if command == self.CMD_CONNECT:

            self.status_bar.info("Connecting to {0}:{1}".format(hostname, port))

            error = self.remote_host.connect(hostname, port)
            if error == HTTPSocks5Adapter.CONNECTION_REFUSED:
                self.status_bar.error('Connection to {0}:{1} refused'.format(hostname, port))
                return False

            elif error == HTTPSocks5Adapter.UNKNOWN_HOST_NAME:
                self.status_bar.error('Unknown hostname {0}'.format(hostname))
                return False

            if error == HTTPSocks5Adapter.HTTP_REQUEST_FAIL:
                self.status_bar.error('Request error - {0}'.format(self.server_uri))
                return False

            elif error != HTTPSocks5Adapter.SUCCESS:
                return False

            response = pack('BBBB', version, 0, 0, addr_type)

            response += raw_addr + pack('H', port)
            self.socket.send(response)

        else:
            # print "[!] Unknown Socks5 command: {0}".format(command)

            self.socket.send(pack('B', packet[0]) + '\xff')
            return False

        return True


    def _main_loop(self):

        _incomming_data = ''

        while self._continue:

            if not _incomming_data:
                _incomming_data = self.remote_host.recv(8192)

            if _incomming_data == None:
                break

            if _incomming_data:
                _to_write = [self.socket, ]
            else:
                _to_write = []

            to_read, to_write,_ = select.select([self.socket, ], _to_write, [], 1)

            if self.socket in to_read:
                data = self.socket.recv(1024)

                if data == '':
                    break

                if not self.remote_host.send(data):
                    break

                self.status_bar.increase_tx(len(data))

            if self.socket in to_write:
                self.socket.sendall(_incomming_data)

                self.status_bar.increase_rx(len(_incomming_data))
                _incomming_data = ''

        # Flush the reminding data and close the connection
        if self._continue:
            self.remote_host.close()


    def stop(self):
        self._continue = False


    def run(self):
        
        if self._handshake():
            self._main_loop()

        self.socket.close()


class StatusBar(Thread):

    def __init__(self, verbosity):
        Thread.__init__(self)

        self.verbosity = verbosity

        self._continue = True
        self._mutex = Lock()

        self._bars = ['-', '\\', '|', '/']
        self._bar_index = 0

        self._prev_output_size = 0
        self._bar_format = "[{bar}] [Tx: ({tx}) - Rx: ({rx})]"
        self._bar_params = {'tx':0, 'rx':0, 'bar':'-'}


    def _write(self, msg):
        sys.stdout.write('\r')
        sys.stdout.write(msg)
        if len(msg) < self._prev_output_size:
            sys.stdout.write(' '*(self._prev_output_size - len(msg)))
        sys.stdout.flush()


    def _update_bar(self):
        _out_str = self._bar_format.format(**self._bar_params)
        self._write(_out_str)
        self._prev_output_size = len(_out_str)


    def done(self):
        if self.verbosity > 0:
            sys.stdout.write('done\n')


    def fail(self):
        if self.verbosity > 0:
            sys.stdout.write('fail\n')


    def checking(self, msg):
        if self.verbosity > 0:
            self._write('[+] ' + msg + ' ... ')
            

    def info(self, msg):
        self._mutex.acquire()

        if self.verbosity > 1:
            self._write('[!] ' + msg + '\n')
            self._update_bar()

        self._mutex.release()


    def error(self, msg):
        self._mutex.acquire()

        if self.verbosity > 0:
            self._write('[e] ' + msg + '\n')
            self._update_bar()

        self._mutex.release()


    def increase_tx(self, amount):
        self._mutex.acquire()

        self._bar_params['tx'] += amount

        self._mutex.release()


    def increase_rx(self, amount):
        self._mutex.acquire()

        self._bar_params['rx'] += amount

        self._mutex.release()


    def stop(self):
        self._continue = False


    def run(self):

        while self._continue:
            self._mutex.acquire()

            self._update_bar()

            self._mutex.release()

            time.sleep(1)

            self._bar_index = (self._bar_index + 1) % 4
            self._bar_params['bar'] = self._bars[self._bar_index]
        print ''


class Server:

    def __init__(self, local_ip, local_port, server_uri, status_bar):
        self.local_ip = local_ip
        self.local_port = local_port
        self.server_uri = server_uri

        self.streams = []

        self.requests_sem = Semaphore(2)
        self.status_bar = status_bar

    def start(self):

        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.status_bar.checking('Binding {0}:{1}'.format(args.local_ip, args.local_port))
        try:
            self.main_socket.bind((self.local_ip, self.local_port))
        except:
            self.status_bar.fail()
            sys.exit(1)

        self.status_bar.done()

        self.main_socket.listen(4)

        self.status_bar.start()

        try:
            while True:

                connection, addr = self.main_socket.accept()

                stream = Socks5Stream(connection, self.requests_sem, self.status_bar, self.server_uri)
                stream.start()

                self.streams.append(stream)
        except Exception as e:
            self.status_bar.error(str(e))
            pass
        except:
            self.status_bar.info('Closing all connections')
            pass

        try:
            self.status_bar.stop()

            for stream in self.streams:
                stream.stop()

            for stream in self.streams:
                stream.join()

            self.main_socket.close()
        except:
            print 'Ok ...'
            pass


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('-u', '--server_uri', default='http://127.0.0.1/bogeyman.php',
                        help='Remote HTTP server where you do the requests.')

    parser.add_argument('-i', '--local_ip', default='127.0.0.1',
                        help='specifies the local address to listen on.')

    parser.add_argument('-p', '--local_port', type=int, default=1080,
                        help='Specifies the local port to listen on.')

    parser.add_argument('-b', '--not_begin', action='store_true',
                        help='Do not start the remote service before start the local.')

    parser.add_argument('-e', '--not_end', action='store_true',
                        help='Do not stop the remote service after stop the local.')

    parser.add_argument('-v', '--verbosity', action="count", default=0,
                        help='Increase output verbosity.')

    args = parser.parse_args()

    status_bar = StatusBar(args.verbosity)

    if not args.not_begin:
        status_bar.checking('Beginning service {0}'.format(args.server_uri))
        if not HTTPSocks5Adapter.begin_service(args.server_uri):
            status_bar.fail()
            sys.exit(-1)
        status_bar.done()
    
    status_bar.checking('Checking service {0}'.format(args.server_uri))
    if not HTTPSocks5Adapter.check_service(args.server_uri):
        status_bar.fail()
        sys.exit(-2)
    status_bar.done()

    server = Server(args.local_ip, args.local_port, args.server_uri, status_bar)

    server.start()

    if not args.not_begin:
        status_bar.checking('Ending service {0}'.format(args.server_uri))
        if not HTTPSocks5Adapter.end_service(args.server_uri):
            status_bar.fail()
            sys.exit(-3)
        status_bar.done()

