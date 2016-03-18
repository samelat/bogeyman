<?php

class Stream {

    public $sock = null;

    public function __construct() {
        $this->sock = 
    }
}

class Tunnel {
    public $streams = array();

    public function __construct() {
        
    }

    public function handler() {

        $running = True;
        $incoming = [];
        $outgoing = [];

        while ($running) {

            @session_start();
            $incoming = array_merge($incoming, $_SESSION['incoming']);
            $_SESSION['outgoing'] = array_merge($_SESSION['outgoing'], $outgoing);
            $running = $_SESSION['running'];
            @session_commit();

            foreach ($incoming as &$message) {
                switch($message['cmd']) {
                    case 'connect':
                        $stream = new Stream($message['host'], $message['port'])
                }
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