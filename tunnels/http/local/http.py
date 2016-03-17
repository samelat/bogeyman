
import json
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

    def set_peer(self, peer):
        self.adapter = peer

    def dispatch(self, message):
        with self.lock:
            self.messages.append(message)
            self.lock.notify_all()

    # Waits until a message arrived or return None if we have to abort.
    def get_message(self):
        with self.lock:
            while not self.messages:
                self.lock.wait()
                if self.stage == 0:
                    return None
        return self.messages.pop(0)

    def handler(self):

        session = requests.Session()

        with self.lock:
            session.cookies = self.cookies.copy()

        while True:
            message = self.get_message()
            if message is None:
                break

            response = session.post(self.url, data=json.dumps(message))
            print(response.text)
            for message in response.json():
                    self.adapter.dispatch(message)

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
        with self.lock:
            session.get(self.url)
            self.cookies = session.cookies

        for index in range(0, self.number_of_threads):
            thread = Thread(target=self.handler)
            thread.start()
            self.threads.append(thread)
