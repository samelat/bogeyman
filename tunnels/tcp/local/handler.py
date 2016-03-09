
import asyncio


class Handler(asyncio.Protocol):

    def __init__(self, tunnel):
        self.tunnel = tunnel
        self.tunnel.handler = self
        self.transport = None

    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('[!] Tunnel connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, message):
        # message = data.decode()
        print('Data received: {}'.format(message))
        # self.tunnel.adapter.dispatch(b'AAAAAAAAAAAAAA')

        # print('Send: {}'.format(message))
        # self.transport.write(data)

        # print('Close the client socket')
        # self.transport.close()
