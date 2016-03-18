<?php

class Stream {

}

class Tunnel {
    public $running = False;
    public $messages = [];
    public $streams = array();

    public function __construct() {
        $this->running = True;
    }

    public function handler() {
        $running = True;
        while ($running) {
            sleep(8);
            @session_start();
            $running = $_SESSION['running'];
            @session_commit();
        }
    }
}

@session_start();

$method = $_SERVER['REQUEST_METHOD'];
if ($method == 'POST') {

    $request = json_decode(file_get_contents('php://input'), true);
    $seq = $request['seq'];
    $message = $request['msg'];

    switch($message['cmd']) {
        case 'start':
            if (!isset($_SESSION['running'])) {
                $_SESSION['running'] = True;
                $_SESSION['seq'] = 0;
                $_SESSION['buffer'] = array();
                $_SESSION['outgoing'] = [];
                @session_commit();

                $tunnel = new Tunnel();
                $tunnel->handler();
            }
            break;

        case 'sync':
            if ($seq == $_SESSION['seq']) {
                array_push($_SESSION['outgoing'], $message);
                $_SESSION['seq']++;
                while (array_key_exists($_SESSION['seq'], $_SESSION['buffer'])) {
                    array_push($_SESSION['outgoing'], $_SESSION['buffer'][$_SESSION['seq']]);
                    unset($_SESSION['buffer'][$_SESSION['seq']]);
                    $_SESSION['seq']++;
                }
            } else {
                $_SESSION['buffer'][$seq] = $message;
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