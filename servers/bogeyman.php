<?php

/*
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>
 *
 *  Author: Gaston Traberg <samelat@gmail.com>
 *
 */

    class Stream {
        public $incomming_buffer = array();
        public $outgoing_buffer  = array();
        public $socket = NULL;

        public function __construct($new_socket) {
            $this->socket = $new_socket;
        }
    }

    /*
    class TCPStream extends Stream {

    }
    */

    /* 
     * Comandos Request
     *    00    - data refresh          - <stream_id>|<outgoing_data>
     *                         Response - <response_code>|<incomming_data>
     *
     *    01    - close socket          - <stream_id>
     *                         Response - <response_code>
     *
     *    02    - create tcp stream     - <hostname><port>
     *                         Response - <response_code>
     *
     *    99    - Halt server           -
     *                         Response - 00
     * 
     * Response codes
     *    00    - OK
     *    01    - Connection Refused
     *    02    - Connection Closed
     *
     *    50    - Malformed request
     *    51    - Unknown command
     *    52    - Unknown parameter
     */
    class Server {

        // Socket layer errors
        const SUCCESS            = 0;
        const CONNECTION_REFUSED = 1;
        const CONNECTION_CLOSED  = 2;
        const UNKNOWN_HOST_NAME  = 3;

        // Protocol errors
        const MALFORMED_REQUEST  = 50;
        const UNKNOWN_COMMAND    = 51;
        const UNKNOWN_PARAMETER  = 52;

        public $streams = array();
        public $continue = true;


        private function make_response($request, &$response_params) {

            $components = explode('|', $request);

            if(count($components) < 2)
                return Server::MALFORMED_REQUEST;

            if(!preg_match('/(?P<command>\d{1,2})/', $components[1], $matches))
                return Server::MALFORMED_REQUEST;

            $command = $matches['command'];

            if(($command == 0) || ($command == 1)) {

                if((count($components) < 3) || (!preg_match('/(?P<stream_id>\d{1,5})/', $components[2], $matches)))
                    return Server::MALFORMED_REQUEST;

                $stream_id = intval($matches['stream_id']);

                if(!isset($this->streams[$stream_id]))
                    return Server::UNKNOWN_PARAMETER;

                // DATA REFRESH
                if($command == 0) {

                    if(count($this->streams[$stream_id]->incomming_buffer) > 0) {

                        $response_params[0] = base64_encode(array_shift($this->streams[$stream_id]->incomming_buffer));

                    } elseif($this->streams[$stream_id]->socket == NULL) {
                            unset($this->streams[$stream_id]);
                            return Server::CONNECTION_CLOSED;
                    }

                    if(isset($components[3]))
                        array_push($this->streams[$stream_id]->outgoing_buffer, base64_decode($components[3]));

                // CLOSE STREAM
                } else {

                    if($this->streams[$stream_id]->socket != NULL)
                        socket_close($this->streams[$stream_id]->socket);
                    unset($this->streams[$stream_id]);
                }

            // CREATE A TCP STREAM
            } elseif($command == 2) {

                if(!preg_match('/(?P<hostname>[^:]+):(?P<port>\d{1,5})/', $components[2], $matches))
                    return Server::MALFORMED_REQUEST;

                $port = intval($matches['port']);
                if($port > 65535)
                    return Server::MALFORMED_REQUEST;
            
                $host_ips = gethostbynamel($matches['hostname']);
                if(!$host_ips)
                    return Server::UNKNOWN_HOST_NAME;

                $new_socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
                
                try {
                    socket_connect($new_socket, $host_ips[0], $port);
                } catch(Exception $e) {
                    return Server::CONNECTION_REFUSED;
                }
            
                $stream_id = (int)$new_socket;

                $this->streams[$stream_id] = new Stream($new_socket);
                $response_params[0] = strval($stream_id);

            // HALT SERVER
            } elseif($command == 99) {

                $this->continue = false;

            } else {
                print_r($this->streams);
                return Server::UNKNOWN_COMMAND;

            }

            return Server::SUCCESS;
        }

        /*********************************************
         *
         */
        private function handle_client($client_socket) {

            $request = socket_read($client_socket, 8192, PHP_BINARY_READ);

            $params = Array();
            $response_code = $this->make_response($request, $params);

            $response = sprintf("|%02d", $response_code);
            for($i = 0; $i < count($params); $i++)
                $response = $response . '|' . $params[$i];

            socket_write($client_socket, $response);

            socket_close($client_socket);
        }

        /*********************************************
         *
         */
        public function start() {

            $main_socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);

            // Socket local para recivir las conexiones de clientes
            try {
                socket_bind($main_socket, '127.0.0.1');
            } catch(Exception $e) {
                return;
            }

            // Informamos al cliente a que puerto local conectarse
            socket_getsockname($main_socket, $local_addr, $local_port);
            file_put_contents('/tmp/port', $local_port);

            socket_listen($main_socket);

            $this->streams[(int)$main_socket] = new Stream($main_socket);

            // MAIN LOOP
            while($this->continue) {

                $active = array_filter($this->streams, function($e){return $e->socket != NULL;});

                $read   = array_map(function($e){return $e->socket;}, $active);
                
                # TODO: Add only the sockets that have data to be sent
                $_with_data = array_filter($active, function($e){return (count($e->outgoing_buffer) > 0);});
                $write  = array_map(function($e){return $e->socket;}, $_with_data);

                $except = NULL;

                socket_select($read, $write, $except, NULL);
                
                // Handle incomming connection
                if(in_array($main_socket, $read)) {
                    $client_socket = socket_accept($main_socket);
                    $this->handle_client($client_socket);
                }
                
                // Incomming data
                foreach($read as $remote_socket) {
                    
                    if($remote_socket == $main_socket)
                        continue;

                    if(!isset($this->streams[(int)$remote_socket]))
                        continue;

                    if(count($this->streams[(int)$remote_socket]->incomming_buffer) > 15)
                        continue;
                    
                    $count = socket_recv($remote_socket, $data, 8192, 0);

                    // if the remote connection has been closed
                    if($count != False) {

                        array_push($this->streams[(int)$remote_socket]->incomming_buffer, $data);
                    } else {
                        socket_close($remote_socket);
                        $this->streams[(int)$remote_socket]->socket = NULL;
                    }
                }

                // Outgoing data
                foreach($write as $remote_socket) {
                    
                    if($remote_socket == $main_socket)
                        continue;

                    if(!isset($this->streams[(int)$remote_socket]))
                        continue;

                    if($this->streams[(int)$remote_socket]->socket == NULL)
                        continue;

                    // if(isset($this->streams[(int)$remote_socket]->outgoing_buffer[0])) {
                    $data = array_shift($this->streams[(int)$remote_socket]->outgoing_buffer);

                    socket_write($remote_socket, $data);
                    // }
                }
            }

            socket_close($main_socket);

            unlink('/tmp/port');
        }
    }

    set_time_limit(0);

    function exceptions_error_handler($severity, $message, $filename, $lineno) { 
        throw new ErrorException($message, 0, $severity, $filename, $lineno); 
    }
    set_error_handler('exceptions_error_handler');

    // SERVER
    if (isset($_GET['server'])) {

        $server = new Server();
        $server->start();

    // CLIENT
    } else {

        if(!isset($_POST['data'])) {
            echo '|90';
            exit();
        }

        $port = file_get_contents('/tmp/port');
        $port = intval($port);

        $client_socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);

        try {
            socket_connect($client_socket, '127.0.0.1', $port);
        } catch(Exception $e) {
            echo '|91';
            exit();
        }

        socket_write($client_socket, $_POST['data']);

        while(true) {

            $read = Array($client_socket);
            $write = $except = NULL;

            socket_select($read, $write, $except, NULL);

            if(in_array($client_socket, $read)) {
                try {
                    $data = socket_read($client_socket, 8192, PHP_BINARY_READ);
                } catch(Exception $e) {
                    // echo '|90';
                    break;
                }

                if($data == '')
                    break;

                echo $data;
            }

        };

        socket_close($client_socket);
    }
?>
