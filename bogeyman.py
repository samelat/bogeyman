
import asyncio
import logging
import argparse

import tunnels
import adapters


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('-p', '--local_port', type=int, default=1080,
                        help='Port where the service listens for connections.')

    parser.add_argument('-i', '--local_ip', default='127.0.0.1',
                        help='specifies the local address to listen on.')

    parser.add_argument('-u', '--server_uri', default='http://127.0.0.1/bogeyman.php',
                        help='Remote HTTP server where you do the requests.')

    parser.add_argument('-b', '--not_begin', action='store_true',
                        help='Do not start the remote service before start the local.')

    parser.add_argument('-e', '--not_end', action='store_true',
                        help='Do not stop the remote service after stop the local.')

    parser.add_argument('-v', '--verbosity', action='count', default=0,
                        help='Increase output verbosity.')

    parser.add_argument('-l', '--log', default='notset',
                        choices=['debug', 'info', 'warning', 'error', 'critical'])

    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    tunnel = tunnels.TCP()
    adapter = adapters.Socks5(args.local_ip, args.local_port)

    tunnel.set_peer(adapter)
    adapter.set_peer(tunnel)

    tunnel_server = tunnel.start(loop)
    adapter_server = adapter.start(loop)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    # Close the services
    tunnel_server.close()
    loop.run_until_complete(tunnel_server.wait_closed())
    adapter_server.close()
    loop.run_until_complete(adapter_server.wait_closed())
    loop.close()
