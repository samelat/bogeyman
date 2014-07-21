import sys
import time
from threading import Lock
from threading import Thread

class StatusBar(Thread):

    def __init__(self, verbosity):
        Thread.__init__(self)

        self.verbosity = verbosity

        self._continue = True
        self._mutex = Lock()

        self._bars = ['-', '\\', '|', '/']
        self._bar_index = 0

        self._prev_output_size = 0
        self._bar_format = "[{bar}] [Tx: ({tx}) - Rx: ({rx})]"
        self._bar_params = {'tx':0, 'rx':0, 'bar':'-'}


    def _write(self, msg):
        sys.stdout.write('\r')
        sys.stdout.write(msg)
        if len(msg) < self._prev_output_size:
            sys.stdout.write(' '*(self._prev_output_size - len(msg)))
        sys.stdout.flush()


    def _update_bar(self):
        _out_str = self._bar_format.format(**self._bar_params)
        self._write(_out_str)
        self._prev_output_size = len(_out_str)


    def done(self):
        if self.verbosity > 0:
            sys.stdout.write('done\n')


    def fail(self):
        if self.verbosity > 0:
            sys.stdout.write('fail\n')


    def checking(self, msg):
        if self.verbosity > 0:
            self._write('[+] ' + msg + ' ... ')
            

    def info(self, msg):
        self._mutex.acquire()

        if self.verbosity > 1:
            self._write('[!] ' + msg + '\n')
            self._update_bar()

        self._mutex.release()


    def error(self, msg):
        self._mutex.acquire()

        if self.verbosity > 0:
            self._write('[e] ' + msg + '\n')
            self._update_bar()

        self._mutex.release()


    def increase_tx(self, amount):
        self._mutex.acquire()

        self._bar_params['tx'] += amount

        self._mutex.release()


    def increase_rx(self, amount):
        self._mutex.acquire()

        self._bar_params['rx'] += amount

        self._mutex.release()


    def stop(self):
        self._continue = False


    def run(self):

        while self._continue:
            self._mutex.acquire()

            self._update_bar()

            self._mutex.release()

            time.sleep(1)

            self._bar_index = (self._bar_index + 1) % 4
            self._bar_params['bar'] = self._bars[self._bar_index]
        print ''