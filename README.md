
Many Thanks to Mauro Soria that is helping me a lot in the development of new components and solving some problems.

How to use it:

1)  Put the script bogeyman.php in the server you want to use as source for the remote connections.

2)  Access the bogeyman.php uri using the 'server' parameter to start the remote service; for example:

        http://10.0.0.20/bogeyman.php?server

3)  Run the local socks5 server by doing the following:

        ./bm_socks5.py -u http://10.0.0.20/bogeyman.php

    Notice that there is no 'server' parameter. This is so because the uri is referring to the Client mode of the php script, not Server mode.

4)  By default, the local server listens to the port 1080.
    You can use any Socks5 client (proxychain, foxyproxy, etc) to connect to this service.
    From now on, any new connection made by this server will be made instead by bogeyman.php.
