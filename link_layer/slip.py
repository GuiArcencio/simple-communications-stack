import traceback

class SLIP:
    ignore_checksum = False

    def __init__(self, serial_lines):
        """
        Instantiate a data link layer with one or more links, each connected
        to a distinct serial line. The argument serial_lines is a dictionary 
        of the form {other_end_ip: serial_line}. The other_end_ip is the IP 
        of the host or router at the link's other end, written as a string of 
        the form 'x.y.z.w'. The serial_line is an object of the PTY class or 
        another one that implements register_receiver and send. 
        """
        self.links = {}
        self.callback = None
        # Constructs a Link for each serial line
        for other_end_ip, serial_line in serial_lines.items():
            link = Link(serial_line)
            self.links[other_end_ip] = link
            link.register_receiver(self._callback)

    def register_receiver(self, callback):
        """
        Register a function to be called when data arrives from the link layer
        """
        self.callback = callback

    def send(self, datagram, next_hop):
        """
        Send datagram to next_hop, whereas next_hop is a IPv4 address given as
        a string of the form 'x.y.z.w'. The link layer will be responsible for
        fiding which link next_hop is located at.
        """
        # Finds the Link capable of reaching next_hop and sends data through it
        self.links[next_hop].send(datagram)

    def _callback(self, datagram):
        if self.callback:
            self.callback(datagram)

_STATE_IDLE = 0
_STATE_READING = 1
_STATE_ESCAPE = 2

class Link:
    def __init__(self, serial_line):
        self.serial_line = serial_line
        self.serial_line.register_receiver(self.__raw_recv)
        self.buffer = b''
        self.state = _STATE_IDLE

    def register_receiver(self, callback):
        self.callback = callback

    def send(self, datagram):
        frame = b''
        for byte in bytearray(datagram):
            byte = byte.to_bytes(1, 'big', signed=False)
            
            if byte == b'\xC0':
                frame = frame + b'\xDB\xDC'
            elif byte == b'\xDB':
                frame = frame + b'\xDB\xDD'
            else:
                frame = frame + byte

        frame = b'\xC0' + frame + b'\xC0'
        self.serial_line.send(frame)

    def __raw_recv(self, data):
        for byte in data:
            byte = byte.to_bytes(1, 'big', signed=False)
            if self.state == _STATE_IDLE:
                if byte == b'\xDB':
                    self.state = _STATE_ESCAPE
                elif byte == b'\xC0':
                    self.state = _STATE_READING
                else:
                    self.buffer = self.buffer + byte
                    self.state = _STATE_READING
            elif self.state == _STATE_READING:
                if byte == b'\xC0':
                    if len(self.buffer) > 0: # Ignoring empty frames
                        try:
                            self.callback(self.buffer)
                        except:
                            # ignores exception, but prints it
                            traceback.print_exc()

                    self.buffer = b''
                    self.state = _STATE_IDLE
                elif byte == b'\xDB':
                    self.state = _STATE_ESCAPE
                else:
                    self.buffer = self.buffer + byte
            elif self.state == _STATE_ESCAPE:
                if byte == b'\xDC':
                    self.buffer = self.buffer + b'\xC0'
                elif byte == b'\xDD':
                    self.buffer = self.buffer + b'\xDB'

                self.state = _STATE_READING
