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

    public $running = False;
    public $incoming = [];
    public $outgoing = [];

    public function __construct() {
        
    }

    public function digest_messages() {
        foreach ($this->incoming as &$message) {
            switch($message['cmd']) {
                case 'connect':
                    $sid = $message['id'];
                    $stream = new Stream($sid);
                    if (socket_set_nonblock($stream->sock)) {
                        socket_connect($stream->sock, $message['host'], $message['port']));
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
    }

    public function handler() {

        while ($this->running) {

            @session_start();
            $this->incoming = array_merge($this->incoming, $_SESSION['incoming']);
            $_SESSION['outgoing'] = array_merge($_SESSION['outgoing'], $this->outgoing);
            $this->outgoing = array();
            $this->running = $_SESSION['running'];
            @session_commit();

            /* Process incoming messages */
            $this->digest_incoming();

            /* Controls pending connections and to read sockets */
            $active_socks = array_map(function($s){return $s->sock;}, $this->streams);
            $connecting_socks = array_map(function($s){return $s->sock;}, $this->connecting_streams);
            socket_select($active_socks, $connecting_socks, null, 1);

            foreach($active_socks as &$sock) {
                $sid = $this->socket_to_sid[$sock];
                $data = $this->streams[$sid]->recv();
                if (count($data) == 0) {
                    array_push($this->outgoing, array('id'=>$sid, 'cmd'=>'status', 'value'=>-2));
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
    $seq = $request['seq'];
    $messages = $request['msgs'];
    $command = $request['cmd'];

    switch($command) {
        case 'start':
            if (!isset($_SESSION['running'])) {
                $_SESSION['running'] = True;
                $_SESSION['seq'] = 0;
                $_SESSION['buffer'] = array();
                $_SESSION['outgoing'] = [];
                $_SESSION['incoming'] = [];
                @session_commit();

                $tunnel = new Tunnel();
                $tunnel->handler();
            }
            break;

        case 'sync':
            if ($seq == $_SESSION['seq']) {
                $_SESSION['outgoing'] = array_merge($_SESSION['outgoing'], $messages);
                $_SESSION['seq']++;

                while (array_key_exists($_SESSION['seq'], $_SESSION['buffer'])) {
                    array_push($_SESSION['outgoing'], $_SESSION['buffer'][$_SESSION['seq']]);
                    $_SESSION['outgoing'] = array_merge($_SESSION['outgoing'], $_SESSION['buffer'][$_SESSION['seq']]);
                    unset($_SESSION['buffer'][$_SESSION['seq']]);
                    $_SESSION['seq']++;
                }

            } else {
                $_SESSION['buffer'][$seq] = $messages;
            }
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