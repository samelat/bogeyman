class Server:

    def __init__(self, local_ip, local_port, server_uri, status_bar):
        self.local_ip = local_ip
        self.local_port = local_port
        self.server_uri = server_uri

        self.streams = []

        self.requests_sem = Semaphore(2)
        self.status_bar = status_bar

    def start(self):

        self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.status_bar.checking('Binding {0}:{1}'.format(args.local_ip, args.local_port))
        try:
            self.main_socket.bind((self.local_ip, self.local_port))
        except:
            self.status_bar.fail()
            sys.exit(1)

        self.status_bar.done()

        self.main_socket.listen(4)

        self.status_bar.start()

        try:
            while True:

                connection, addr = self.main_socket.accept()

                stream = Socks5Stream(connection, self.requests_sem, self.status_bar, self.server_uri)
                stream.start()

                self.streams.append(stream)
        except Exception as e:
            self.status_bar.error(str(e))
            pass
        except:
            self.status_bar.info('Closing all connections')
            pass

        try:
            self.status_bar.stop()

            for stream in self.streams:
                stream.stop()

            for stream in self.streams:
                stream.join()

            self.main_socket.close()
        except:
            print 'Ok ...'
            pass