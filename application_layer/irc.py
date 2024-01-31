import re
import asyncio
from threading import Lock

class IRCServer:
    def __init__(self, tcp_server):
        self._connections = {}
        self._channels = {}
        self._datamutex = Lock()

        tcp_server.register_accepted_connections_monitor(self.accepted_connection)

    def run(self):
        asyncio.get_event_loop().run_forever()

    def data_received(self, connection, data):
        if data == b'':
            return self.connection_left(connection)
        
        client_ip = connection.connection_id[0]
        client_port = connection.connection_id[1]

        connection._residue = connection._residue + data

        message, separator, rest = connection._residue.partition(b'\r\n')
        while separator != b'':
            print(f'Message received from {client_ip}:{client_port}: {message}')

            self.interpret_message(connection, message)

            connection._residue = rest
            message, separator, rest = connection._residue.partition(b'\r\n')

    def accepted_connection(self, connection):
        client_ip = connection.connection_id[0]
        client_port = connection.connection_id[1]
        print(f'New connection from {client_ip}:{client_port}')

        connection._residue = b''
        connection._nickname = b'*'
        connection._channels = set()
        connection.register_receiver(self.data_received)

    def connection_left(self, connection):
        self.process_exit(connection)

        client_ip = connection.connection_id[0]
        client_port = connection.connection_id[1]
        print(f'Connection closed with {client_ip}:{client_port}')

        connection.close()

    def validate_nickname(self, nickname):
        return re.match(br'^[a-zA-Z][a-zA-Z0-9_-]*$', nickname) is not None
    
    def interpret_message(self, connection, msg):
        fields = msg.strip(b' \r\n').split(b' ')
        if len(fields) < 2: return

        verb = fields[0].upper()
        if verb == b'PING':
            self.process_ping(connection, b' '.join(fields[1:]))
        elif verb == b'NICK':
            self.process_nick(connection, fields[1])
        elif verb == b'PRIVMSG' and len(fields) >= 3:
            if fields[1][0:1] == b'#':
                self.process_channel_privmsg(connection, fields[1], b' '.join(fields[2:]))
            else:
                self.process_personal_privmsg(connection, fields[1], b' '.join(fields[2:]))
        elif verb == b'JOIN' and connection._nickname != b'*':
            self.process_join(connection, fields[1])
        elif verb == b'PART':
            self.process_part(connection, fields[1])

    def process_ping(self, connection, payload):
        connection.send(b':server PONG server :%s\r\n' % payload)
    
    def process_nick(self, connection, nickname):
        if not self.validate_nickname(nickname):
            connection.enviar(b':server 432 %s %s :Erroneous nickname\r\n' % (connection._nickname, nickname))
            return
        
        self._datamutex.acquire()
        available = self.try_new_nickname(connection, nickname)
        self._datamutex.release()

        if available:
            if connection._nickname == b'*':
                connection.send(b':server 001 %s :Welcome\r\n' % nickname)
                connection.send(b':server 422 %s :MOTD File is missing\r\n' % nickname)
            else:
                self._datamutex.acquire()
                colleagues = self.find_colleagues(connection)
                self._datamutex.release()

                messages = set()
                for colleague in colleagues:
                    message = asyncio.create_task(
                        self.send_async(
                            colleague,
                            b':%s NICK %s\r\n' % (connection._nickname, nickname)
                        )
                    )
                    messages.add(message)
                    message.add_done_callback(messages.discard)

            connection._nickname = nickname 
        else:
            connection.send(b':server 433 %s %s :Nickname is already in use\r\n' % (connection._nickname, nickname))

    def process_personal_privmsg(self, connection, recipient, content):
        if connection._nickname != b'*' and len(content) >= 2 and content[0:1] == b':':
            self._datamutex.acquire()
            recipient_connection = self.search_recipient(recipient)
            self._datamutex.release()

            if recipient_connection is not None:
                recipient_connection.send(b':%s PRIVMSG %s %s\r\n' % (connection._nickname, recipient_connection._nickname, content))

    def process_channel_privmsg(self, connection, channel, content):
        if connection._nickname != b'*' and len(content) >= 2 and content[0:1] == b':':
            self._datamutex.acquire()
            channel_connections = self.search_channel(channel)
            self._datamutex.release()

            if channel_connections is not None:
                messages = set()
                for member in channel_connections:
                    if member is not connection:
                        message = asyncio.create_task(
                            self.send_async(
                                member,
                                b':%s PRIVMSG %s %s\r\n' % (connection._nickname, channel.lower(), content)
                            )
                        )
                        messages.add(message)
                        message.add_done_callback(messages.discard)

    def process_join(self, connection, channel):
        if channel[0:1] == b'#' and self.validate_nickname(channel[1:]):
            self._datamutex.acquire()
            members = self.add_member_to_channel(connection, channel)
            self._datamutex.release()
            connection._channels.add(channel.lower())

            messages = set()
            for member in members:
                if member is not connection:
                    message = asyncio.create_task(
                        self.send_async(
                            member,
                            b':%s JOIN :%s\r\n' % (connection._nickname, channel.lower())
                        )
                    )
                    messages.add(message)
                    message.add_done_callback(messages.discard)
            connection.send(b':%s JOIN :%s\r\n' % (connection._nickname, channel.lower()))

            member_names = sorted(list(map((lambda c: c._nickname.lower()), members)))
            msg_buffer = b':server 353 %s = %s :' % (connection._nickname, channel.lower())
            for name in member_names:
                if len(msg_buffer + name) < 510:
                    msg_buffer = msg_buffer + name + b' '
                else:
                    msg_buffer = msg_buffer[:-1] + b'\r\n'
                    connection.send(msg_buffer)
                    msg_buffer = b':server 353 %s = %s :%s ' % (connection._nickname, channel.lower(), name)
            
            msg_buffer = msg_buffer[:-1] + b'\r\n'
            connection.send(msg_buffer)
            connection.send(b':server 366 %s %s :End of /NAMES list.\r\n' % (connection._nickname, channel.lower()))
        else:
            connection.send(b':server 403 %s :No such channel\r\n' % channel)

    def process_part(self, connection, channel):
        channel = channel.lower()
        if channel in connection._channels:
            self._datamutex.acquire()
            members = self.remove_channel_member(connection, channel)
            self._datamutex.release()
            connection._channels.remove(channel)

            messages = set()
            for member in members:
                message = asyncio.create_task(
                    self.send_async(
                        member,
                        b':%s PART %s\r\n' % (connection._nickname, channel.lower())
                    )
                )
                messages.add(message)
                message.add_done_callback(messages.discard)

            connection.send(b':%s PART %s\r\n' % (connection._nickname, channel.lower()))
    
    def process_exit(self, connection):
        self._datamutex.acquire()
        colleagues = self.remove_from_every_channel(connection)
        self._datamutex.release()

        messages = set()
        for colleague in colleagues:
            message = asyncio.create_task(
                self.send_async(
                    colleague,
                    b':%s QUIT :Connection closed\r\n' % connection._nickname
                )
            )
            messages.add(message)
            message.add_done_callback(messages.discard)

    async def send_async(self, connection, data):
        return connection.send(data)
    
    def try_new_nickname(self, connection, nickname):
        current_nickname = connection._nickname
        if nickname.lower() in self._connections.keys():
            return False
        
        if current_nickname != b'*':
            self._connections.pop(current_nickname.lower())

        self._connections[nickname.lower()] = connection
        return True
    
    def search_recipient(self, recipient):
        return self._connections.get(recipient.lower(), None)
    
    def search_channel(self, channel):
        return self._channels.get(channel.lower(), None)
    
    def add_member_to_channel(self, connection, channel):
        channel = channel.lower()

        if channel not in self._channels.keys():
            self._channels[channel] = set()

        self._channels[channel].add(connection)
        return self._channels[channel]
    
    def remove_channel_member(self, connection, channel):
        channel = channel.lower()
        self._channels[channel].remove(connection)
        if len(self._channels[channel]) == 0:
            self._channels.pop(channel)
            return set()
        
        return self._channels[channel]
    
    def remove_from_every_channel(self, connection):
        colleagues = set()
        for channel in connection._channels:
            colleagues.update(self.remove_channel_member(connection, channel))

        if connection._nickname != b'*':
            self._connections.pop(connection._nickname)

        return colleagues
    
    def find_colleagues(self, connection):
        colleagues = set()
        colleagues.add(connection)

        for channel in connection._channels:
            colleagues.update(self._channels[channel])

        return colleagues