
import requests
from threading import Thread, Condition


class HTTP:

    def __init__(self, params):
        self.url = params.get('url', 'http://127.0.0.1')
        self.number_of_threads = int(params.get('threads'), 1)

        self.running = True
        self.threads = []
        self.lock = Condition()
        self.messages = []

    def dispatch(self, message):
        with self.lock:
            self.messages.append(message)
            self.lock.notify_all()

    def handler(self):
        while True:
            with self.lock:
                if not self.running:
                    break

            pass

    def start(self, loop):
        for index in range(0, self.number_of_threads):
            thread = Thread(target=self.handler)
            thread.start()
            self.threads.append(thread)
