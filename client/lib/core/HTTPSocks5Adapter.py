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

