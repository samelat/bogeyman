
import requests
from threading import Thread


class HTTP:

    def __init__(self, params):
        self.url = params.get('url', 'http://127.0.0.1')

    def start(self, loop):
        pass
