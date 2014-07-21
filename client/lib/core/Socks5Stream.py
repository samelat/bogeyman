from threading import Thread
from struct import unpack, pack
import select
from .HTTPSocks5Adapter import *

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