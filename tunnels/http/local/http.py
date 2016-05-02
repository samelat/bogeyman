
import time
import json
import socket
import logging
import requests
import traceback
import threading
from threading import Thread, Condition


class HTTP:

    def __init__(self, url, threads=1):
        self.url = url
        self.number_of_threads = threads
        self.loop = None

        # Stage 2: Trying to reconnect tunnel
        # Stage 1: Tunnel is working
        # Stage 0: Aborting
        self.stage = 2
        self.adapter = None
        self.threads = []
        self.delay = 0
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
            self.delay = 0
            self.lock.notify_all()

    # Waits until a bulk of messages arrived or return seq=-1 if we have to abort.
    def get_bulk(self):
        with self.lock:
            # This is not the only reason "delay" should be zero.
            # if self.messages:
            #     self.delay = 0

            begin = time.time()
            while self.delay:
                self.lock.wait(self.delay)
                if (self.stage == 0) or (time.time() - begin) > self.delay:
                    break

            if self.stage == 0:
                return -1, []

            self.delay = self.delay + 1.0 if self.delay < 8.0 else 8.0

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
            # Get a bulk of messages to send.
            seq, bulk = self.get_bulk()
            if seq < 0:
                break

            # Wrap the bulk into another message (an http tunnel message)
            data = json.dumps({'cmd': 'sync', 'msgs': bulk, 'seq': seq})
            logging.debug('request data: {}'.format(data))
            try:
                result = session.post(self.url, data=data)
            except requests.exceptions.ConnectionError:
                logging.critical('tunnel exception: \n{}'.format(traceback.format_exc()))
                self.loop.stop()
                break
            response = result.json()

            with self.lock:
                if response['msgs']:
                    self.delay = 0
                # Our sequence number should be the next one.
                while self.i_sequence < response['seq']:
                    logging.debug('waiting for sequence number synchronization')
                    self.lock.wait()
                for message in response['msgs']:
                    self.adapter.dispatch(message)
                self.i_sequence += 1
                self.lock.notify_all()

    def stop(self):
        if self.stage == 0:
            return

        with self.lock:
            self.stage = 0
            self.lock.notify_all()
        current_id = threading.get_ident()
        logging.info('stopping threads ...')
        for thread in self.threads:
            if current_id == thread.ident:
                continue
            thread.join()
        logging.info('threads stopped')

        logging.info('stopping remote loop')
        session = requests.Session()
        session.cookies = self.cookies
        session.post(self.url, data='{"cmd":"stop"}')
        time.sleep(0.5)
        session.delete(self.url)
        logging.info('remote loop stopped')

    def start(self, loop):
        self.loop = loop
        session = requests.Session()

        # Create session
        session.get(self.url)
        self.cookies = session.cookies
        logging.debug('cookies: {}'.format(self.cookies))

        # Start remote session loop
        try:
            session.post(self.url, data='{"cmd": "start"}', timeout=1)
        except socket.timeout:
            pass

        for index in range(0, self.number_of_threads):
            thread = Thread(target=self.handler)
            thread.start()
            self.threads.append(thread)
