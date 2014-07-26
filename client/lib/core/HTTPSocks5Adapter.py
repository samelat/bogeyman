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
import thirdparty.requests as requests
import socket
import ssl
import urllib
import urllib2
import urlparse
import time

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

        parsed = urlparse.urlparse(http_host)
        try:
            self.vhost = parsed.netloc.split(':')[0]
            self.port = int(parsed.netloc.split(':')[1])
        except IndexError:
            if parsed.scheme == 'https':
                self.port = 443
            else:
                self.port = 80

        self.ip_addr = socket.gethostbyname(self.vhost)
        self.http_host = '{0}://{1}:{2}{3}'.format(parsed.scheme, self.ip_addr, self.port, parsed.path)
        self.headers = {'Host' : self.vhost}
        self.requests_session = requests.Session()
        self.incomming_data = []
        self.outgoing_data  = []

        self.stream_id = None

        self._delay = 0

        self.hostname = None
        self.hostport = None

    @staticmethod
    def check_service(http_host):
        try:
            response = requests.get(http_host, verify=False)
        except urllib2.HTTPError as e:
            return False

        if response.content == '|90':
            return True
        return False

    @staticmethod
    def begin_service(http_host):
        try:
            response = requests.get(http_host + '?server', timeout=4, verify=False)
        except requests.exceptions.Timeout:
            return True
        except urllib2.HTTPError as e:
            return False

        return False

    @staticmethod
    def end_service(http_host):
        post_data = { 'data' : '|{0}'.format(HTTPSocks5Adapter.END_SERVICE)}
        try:
            response = requests.post(http_host, data=post_data, verify=False)
        except urllib2.HTTPError as e:
            return False
        if response.content == '|00':
            return True
        return False


    def connect(self, host, port):

        if self.stream_id:
            return -1

        self.hostname = host
        self.hostport = port

        post_data = { 'data' : '|02|{0}:{1}'.format(host, port)}

        self.requests_sem.acquire()
        try:
            response = requests.post(self.http_host, data=post_data, headers=self.headers, verify=False)
        except urllib2.HTTPError as e:
            return self.HTTP_REQUEST_FAIL
        finally:
            self.requests_sem.release()

        data = response.content

        response = data.split('|')

        response_code = int(response[1])

        # TODO: ERROR HANDLING
        if response_code == self.SUCCESS:
            self.stream_id = response[2]
        else:
            return response_code

        return self.SUCCESS


    def _update_data(self):
        post_data = {'data' : '|00|{0}'.format(self.stream_id)}
        if self.outgoing_data:
            data = self.outgoing_data.pop(0).encode('base64')
            post_data['data'] += '|{0}'.format(data)

        self.requests_sem.acquire()
        try:
            response = requests.post(self.http_host, data=post_data, headers=self.headers, verify=False)
        #except urllib2.HTTPError as e:
        #    self.stream_id = None
        #    return False
        finally:
            self.requests_sem.release()

        data = response.content

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

        post_data = {'data' : '|01|{0}'.format(self.stream_id)}
        self.requests_sem.acquire()
        response = self.requests_session.post(self.http_host, data=post_data, verify=False)
        self.requests_sem.release()
