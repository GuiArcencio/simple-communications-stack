# Simple Communications Stack

This is a simplified implementation of the OSI communication layers, made as an assignment during my Computer Networks course. The layers are:
- **Physical:** implemented as a PTY.
- **Data link:** implemented over the Serial Line Internet Protocol (SLIP).
- **Network:** implemented over the Internet Protocol (IP).
- **Transport:** implemented over the Transmission Control Protocol (TCP).
- **Application:** implemented as an Internet Relay Chat (IRC) server.

Note that those implementations, especially TCP and IRC, are simplified and may not work in some or even most real situations.

To start the IRC Server on your machine, run `python run_irc.py` and follow the instructions. You can test the server as a client using `nc -C 192.168.123.2 7000` (don't forget the carriage return!).