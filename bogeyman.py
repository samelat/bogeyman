#!/usr/bin/python3

import asyncio
import logging
import argparse

import tunnels
import adapters


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int, default=1080,
                        help='adapter port.')

    parser.add_argument('-a', '--address', default='127.0.0.1',
                        help='adapter interface.')

    parser.add_argument('-l', '--log', default='info',
                        choices=['debug', 'info', 'warning', 'error', 'critical'],
                        help='logging level')

    parser.add_argument('-t', '--tunnel', default='tcp',
                        choices=['tcp', 'http'],
                        help='tunnel module')

    parser.add_argument('parameters', nargs='*', help='tunnel parameters')

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log.upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    params = dict([tuple(param.split('=')[:2]) if '=' in param else (param, None) for param in args.parameters])
    tunnel = tunnels.TCP(params)

    adapter = adapters.Socks5(args.address, args.port)

    tunnel.set_peer(adapter)
    adapter.set_peer(tunnel)

    loop = asyncio.get_event_loop()
    tunnel.start(loop)
    adapter.start(loop)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
