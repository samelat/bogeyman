#!/usr/bin/python3

import time
import asyncio
import logging
import argparse
import traceback
import configparser

import tunnels
import adapters


if __name__ == '__main__':

    # General arguments
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', '--adapter-ip', help='adapter ip address (default: 127.0.0.1)')
    parser.add_argument('-p', '--adapter-port', type=int, help='adapter port (default: 1080)')
    parser.add_argument('-l', '--log', help='log level (default: info)',
                        choices=['debug', 'info', 'warning', 'error', 'critical'])
    parser.add_argument('-c', '--config', help='uses a configuration file')

    tunnel_parser = parser.add_subparsers(dest='tunnel', help='tunnel types (default: tcp)')

    # TCP Parameters
    tcp_parser = tunnel_parser.add_parser('tcp', help='tunnel over TCP')
    tcp_parser.add_argument('-I', '--tunnel-ip', help='address interface (default: 127.0.0.1)')
    tcp_parser.add_argument('-P', '--tunnel-port', help='connection port (default: 8888)', type=int)
    tcp_parser.add_argument('-R', '--reverse', help='use reverse connection', action='store_true')

    # HTTP Parameters
    http_parser = tunnel_parser.add_parser('http', help='tunnel over HTTP')
    http_parser.add_argument('-U', '--url', help='remote script url (default: http://127.0.0.1/remote.php)')
    http_parser.add_argument('-T', '--threads', help='number of threads (default: 2)')

    args = parser.parse_args()

    # Default configuration
    config = {'adapter_ip': '127.0.0.1', 'adapter_port': 1080, 'adapter': 'socks5', 'log': 'info', 'tunnel': 'tcp'}
    file_params = {}

    print(args)

    # Config file configuration
    if args.config is not None:
        config_file = configparser.ConfigParser(allow_no_value=True)
        if config_file.read(args.config):
            # General configuration
            if 'general' in config_file:
                for option, value in config_file['general'].items():
                    config[option.lower()] = value

            # Tunnel configuration
            if config['tunnel'] in config_file:
                for option, value in config_file[config['tunnel']].items():
                    file_params[option.lower()] = value

    # General configuration
    for option in ['adapter_ip', 'adapter_port', 'log', 'tunnel']:
        value = getattr(args, option)
        config[option] = value if value is not None else config[option]

    # Tunnel parameters
    if config['tunnel'] == 'tcp':
        params = {'tunnel_ip': '127.0.0.1', 'tunnel_port': 8888}
        params.update(file_params)
        params['tunnel_ip'] = args.tunnel_ip if args.tunnel_ip is not None else params['tunnel_ip']
        params['tunnel_port'] = args.tunnel_port if args.tunnel_port is not None else params['tunnel_port']
        params['reverse'] = args.reverse

    elif config['tunnel'] == 'http':
        params = {'url': 'http://127.0.0.1/remote.php', 'threads': 2}
        params.update(file_params)
        params['url'] = args.url if args.url is not None else params['url']
        params['threads'] = args.threads if args.threads is not None else params['threads']

    # Starts program
    logging.basicConfig(level=getattr(logging, config['log'].upper()),
                        format='[%(levelname)-0.1s][%(module)s] %(message)s')

    # Configure tunnel
    tunnel_class = getattr(tunnels, config['tunnel'].upper())
    tunnel = tunnel_class(**params)

    # Configure adapter
    adapter = adapters.Socks5(config['adapter_ip'], int(config['adapter_port']))

    tunnel.set_peer(adapter)
    adapter.set_peer(tunnel)

    loop = asyncio.get_event_loop()
    tunnel.start(loop)
    adapter.start(loop)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info('stopping server')
    except Exception:
        logging.critical('unknown exception: \n{}'.format(traceback.format_exc()))

    adapter.stop()
    tunnel.stop()

    if not loop.is_closed():
        loop.stop()
