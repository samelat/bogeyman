#!/usr/bin/python3

import asyncio
import logging
import argparse
import configparser

import tunnels
import adapters


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--port', type=int,
                        help='adapter port (default: 1080)')

    parser.add_argument('-i', '--ip',
                        help='adapter ip address (default: 127.0.0.1)')

    parser.add_argument('-l', '--log',
                        choices=['debug', 'info', 'warning', 'error', 'critical'],
                        help='log level (default: info)')

    parser.add_argument('-t', '--tunnel', choices=['tcp', 'http'],
                        help='tunnel module (default: tcp)')

    parser.add_argument('-c', '--config', default='',
                        help='uses a configuration file')

    parser.add_argument('parameters', nargs='*', help='tunnel parameters')

    args = parser.parse_args()

    # Default configuration
    config = {'ip': '127.0.0.1', 'port': 1080, 'adapter': 'socks5', 'tunnel': 'tcp', 'log': 'info'}
    # Tunnel params
    params = {}

    # Config file configuration
    if args.config:
        config_file = configparser.ConfigParser(allow_no_value=True)
        if config_file.read(args.config):
            # General configuration
            if 'general' in config_file:
                general = config_file['general']
                for option in ['ip', 'port', 'adapter', 'tunnel', 'log']:
                    config[option] = general[option] if option in general else config[option]

            # Tunnel configuration
            if config['tunnel'] in config_file:
                for key, value in config_file[config['tunnel']].items():
                    params[key.lower()] = value if value is None else value.lower()

    # Arguments configuration
    params.update(dict([tuple(param.lower().split('=')[:2])
                        if '=' in param else (param, None) for param in args.parameters]))

    for option in ['ip', 'port', 'tunnel', 'log']:
        value = getattr(args, option)
        config[option] = value if value else config[option]

    # Starts program
    logging.basicConfig(level=getattr(logging, config['log'].upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    tunnel_class = getattr(tunnels, config['tunnel'].upper())
    tunnel = tunnel_class(params)

    adapter = adapters.Socks5(config['ip'], int(config['port']))

    tunnel.set_peer(adapter)
    adapter.set_peer(tunnel)

    loop = asyncio.get_event_loop()
    tunnel.start(loop)
    adapter.start(loop)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    adapter.stop()
    tunnel.stop()

    loop.stop()
