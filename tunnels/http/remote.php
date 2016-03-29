<?php

class Stream {

    public $sid = null;
    public $sock = null;

    public function __construct($sid) {
        $this->sid = $sid;
        $this->sock = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
    }

    public function send($data) {

    }
}

class Tunnel {
    public $streams = array();
    public $socket_to_sid = array();
    public $connecting_streams = array();

    public $running = true;
    public $incoming = [];
    public $outgoing = [];

    public function __construct() {
        
    }

    public function digest_incoming() {
        foreach ($this->incoming as $message) {
            switch($message['cmd']) {
                case 'connect':
                    $sid = $message['id'];
                    $stream = new Stream($sid);
                    # if (socket_set_nonblock($stream->sock)) {
                    if (true) {
                        socket_connect($stream->sock, $message['host'], $message['port']);
                        $this->connecting_streams[$sid] = $stream;
                        $this->socket_to_sid[$stream->sock] = $sid;
                    } else {
                        $msg = array('id'=>$this->sid, 'cmd'=>'status', 'value'=>-2);
                        array_push($this->outgoing, $msg);
                    }
                    break;

                case 'sync':
                    $sid = $message['id'];
                    if (array_key_exists($sid, $this->streams)) {
                        $data = json_decode($message['data']);
                        if (!$this->streams[$sid]->send($data)) {
                            $msg = array('id'=>$this->sid, 'cmd'=>'status', 'value'=>-2);
                            array_push($this->outgoing, $msg);
                        }
                    }
            }
        }
        $this->incoming = array();
    }

    public function handler() {

        while ($this->running) {

            @session_start();
            $this->incoming = array_merge($this->incoming, $_SESSION['incoming']);
            $_SESSION['incoming'] = array();
            $_SESSION['outgoing'] = array_merge($_SESSION['outgoing'], $this->outgoing);
            $this->outgoing = array();
            $this->running = $_SESSION['running'];
            @session_commit();

            /* Process incoming messages */
            $this->digest_incoming();

            /* Controls pending connections and to read sockets */
            $active_socks = array_map(function($s){return $s->sock;}, $this->streams);
            $connecting_socks = array_map(function($s){return $s->sock;}, $this->connecting_streams);
            $excepts = NULL;
            print_r($active_socks);
            print_r($connecting_socks);
            socket_select($active_socks, $connecting_socks, $excepts, 1);

            # break;

            foreach($connecting_socks as $sock) {
                $sid = $this->socket_to_sid[$sock];
                $error = socket_last_error($sock);

                array_push($this->outgoing, array('id'=>$sid, 'cmd'=>'status', 'value'=>$error));

                if ($error == 0) {
                    $this->streams[$sid] = $this->connecting_streams[$sid];
                } else {
                    socket_close($sock);
                }

                unset($this->connecting_streams[$sid]);
            }

            foreach($active_socks as $sock) {
                $sid = $this->socket_to_sid[$sock];
                $data = $this->streams[$sid]->recv();
                if (count($data) == 0) {
                    array_push($this->outgoing, array('id'=>$sid, 'cmd'=>'status', 'value'=>-2));
                    socket_close($sock);
                    unset($this->streams[$sid]);
                    unset($this->socket_to_sid[$sock]);
                    continue;
                }
                $data = json_encode($data);
                array_push($this->outgoing, array('id'=>$sid, 'cmd'=>'sync', 'data'=>$data));
            }
        }
    }
}

@session_start();

$method = $_SERVER['REQUEST_METHOD'];
if ($method == 'POST') {

    $request = json_decode(file_get_contents('php://input'), true);

    switch($request['cmd']) {
        case 'start':
            if (!isset($_SESSION['running'])) {
                $_SESSION['running'] = true;
                $_SESSION['i_seq'] = 0; # Incoming sequence number
                $_SESSION['o_seq'] = 0; # Outgoing sequence number
                $_SESSION['buffer'] = array();
                $_SESSION['outgoing'] = [];
                $_SESSION['incoming'] = [];
                @session_commit();

                set_time_limit(0);
                ob_end_clean();
                header("Connection: close");
                ignore_user_abort();
                ob_start();
                $size = ob_get_length();
                header("Content-Length: $size");
                ob_end_flush();
                flush();
                session_write_close();

                $tunnel = new Tunnel();
                $tunnel->handler();
                echo ":S";
            }
            break;

        case 'sync':
            $seq = $request['seq'];
            $messages = $request['msgs'];

            if ($seq == $_SESSION['i_seq']) {
                $_SESSION['incoming'] = array_merge($_SESSION['incoming'], $messages);
                $_SESSION['i_seq']++;

                while (array_key_exists($_SESSION['i_seq'], $_SESSION['buffer'])) {
                    $_SESSION['incoming'] = array_merge($_SESSION['incoming'], $_SESSION['buffer'][$_SESSION['i_seq']]);
                    unset($_SESSION['buffer'][$_SESSION['i_seq']]);
                    $_SESSION['i_seq']++;
                }

            } elseif ($seq > $_SESSION['i_seq']) {
                $_SESSION['buffer'][$seq] = $messages;

            } else {
                break;
            }

            $msgs = array_slice($_SESSION['outgoing'], 0, 64);
            $_SESSION['outgoing'] = array_slice($_SESSION['outgoing'], 64);

            $response = array('seq'=>$_SESSION['o_seq'], 'cmd'=>'sync', 'msgs'=>$msgs);
            $_SESSION['o_seq'] += 1;

            echo json_encode($response);

            break;

        case 'stop':
            $_SESSION['running'] = False;
    }

} elseif($method == 'DELETE') {
    session_destroy();

} else {
    echo json_encode($_SESSION);
}

?>