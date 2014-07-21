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
from threading import Semaphore
from lib.core import *
from lib.output import *


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
