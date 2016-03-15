
import json
import requests
import threading
from threading import Thread, Condition


class HTTP:

    def __init__(self, params):
        self.url = params.get('url', 'http://127.0.0.1/remote.php')
        self.number_of_threads = int(params.get('threads'), 1)

        self.adapter = None
        self.running = True
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

    def handler(self):

        session = requests.Session()

        with self.lock:
            session.cookies = self.cookies.copy()

        while True:
            with self.lock:
                if not self.running:
                    break
                message = self.messages.pop(0)

            response = session.post(self.url, data=json.dumps(message))
            messages = response.json()
            if messages:
                for message in messages:
                    pass

    def stop(self):
        with self.lock:
            self.running = False
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
