
import json
import socket
import requests
import threading
from threading import Thread, Condition


class HTTP:

    def __init__(self, params):
        self.url = params.get('url', 'http://127.0.0.1/remote.php')
        self.number_of_threads = int(params.get('threads', 1))

        # Stage 2: Trying to reconnect tunnel
        # Stage 1: Tunnel is working
        # Stage 0: Aborting
        self.stage = 2
        self.adapter = None
        self.threads = []
        self.lock = Condition()

        self.messages = []
        self.cookies = None
        self.buffer = {}
        # This will keep the messages in order
        self.i_sequence = 0
        self.o_sequence = 0

    def set_peer(self, peer):
        self.adapter = peer

    def dispatch(self, message):
        with self.lock:
            self.messages.append(message)
            self.lock.notify_all()

    # Waits until a bulk of messages arrived or return None if we have to abort.
    def get_bulk(self):
        with self.lock:
            if not self.messages:
                self.lock.wait(1.0)

            if self.stage == 0:
                return -1, []

            bulk = self.messages[:64]
            self.messages = self.messages[64:]
            seq = self.o_sequence
            self.o_sequence += 1

        return seq, bulk

    def handler(self):
        session = requests.Session()

        with self.lock:
            session.cookies = self.cookies.copy()

        while True:
            seq, bulk = self.get_bulk()
            if seq < 0:
                break

            # Sends the bulk into another message
            data = json.dumps({'cmd': 'sync', 'msgs': bulk, 'seq': seq})
            print('[!] DATA: {}'.format(data))
            result = session.post(self.url, data=data)
            print(result.text)
            response = result.json()
            print(response)
            with self.lock:
                while self.i_sequence < response['seq']:
                    print(self.i_sequence)
                    print('se clava esperando...')
                    self.lock.wait()
                for message in response['msgs']:
                    self.adapter.dispatch(message)
                self.i_sequence += 1

    def stop(self):
        with self.lock:
            self.stage = 0
            self.lock.notify_all()
        current_id = threading.get_ident()
        for thread in self.threads:
            if current_id == thread.ident:
                continue
            thread.join()

    def start(self, loop):
        session = requests.Session()

        # Create session
        session.get(self.url)
        self.cookies = session.cookies
        print(self.cookies)

        # Start remote session loop
        try:
            session.post(self.url, data='{"cmd": "start"}', timeout=0.5)
        except socket.timeout:
            pass

        for index in range(0, self.number_of_threads):
            thread = Thread(target=self.handler)
            thread.start()
            self.threads.append(thread)
