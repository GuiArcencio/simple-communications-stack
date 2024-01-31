import asyncio
from random import randint
from time import time
from utils.tcp import *

class TCPServer:
    def __init__(self, network, port):
        self.network = network
        self.port = port
        self.connections = {}
        self.callback = None
        self.network.register_receiver(self._rdt_rcv)

    def register_accepted_connections_monitor(self, callback):
        """
        Used by the application layer to register a function to be called whenever
        a new connection is accepted.
        """
        self.callback = callback

    def _rdt_rcv(self, src_addr, dst_addr, segment):
        src_port, dst_port, seq_no, ack_no, \
            flags, window_size, _, _ = read_header(segment)

        if dst_port != self.port:
            # Ignore segments not sent to this server's port
            return
        if not self.network.ignore_checksum and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('discarding segment with incorrect checksum')
            return

        payload = segment[4*(flags>>12):]
        connection_id = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            # SYN flag set, client establishing newconnection
            conexao = self.connections[connection_id] = \
                Connection(self, connection_id, seq_no, window_size)

            if self.callback:
                self.callback(conexao)
        elif connection_id in self.connections:
            # Sends packet to correct connection
            self.connections[connection_id]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (packet addressed to unknown connection)' %
                  (src_addr, src_port, dst_addr, dst_port))
            
    def remove_connection(self, connection_id):
        self.connections.pop(connection_id, None)

ALPHA = 0.125
BETA = 0.25
class Connection:
    def __init__(self, tcp_server, connection_id, seq_no, window_size):
        self.server = tcp_server
        self.connection_id = connection_id
        self.callback = None
        self.timer = None
        self.unacked_segments = []
        self.sending_queue = []
        self.estimated_rtt = None
        self.dev_rtt = None
        self.current_window_size = 1 # * MSS
        self.current_seq_no = randint(0, 0xffff)
        self.last_acked_no = self.current_seq_no
        self.expected_seq_no = seq_no + 1
        self.ready_to_close = False
        self.handshake_complete = False

        # Responde com SYNACK para a abertura de conexão
        # Respond with SYNACK to connection opening
        self._send_segment(
            FLAGS_SYN | FLAGS_ACK,
            b'',
        )

    def _timeout_interval(self):
        """
        Calcula o timeout com base no RTT estimado
        """
        """
        Calculate timeout interval using estimated RTT
        """
        if self.estimated_rtt is None:
            return 3
        else:
            return self.estimated_rtt + 4 * self.dev_rtt
        
    def _estimate_rtt(self, sample_rtt):
        """
        New estimate for RTT
        """
        if not self.handshake_complete:
            # Não use o ACK de abertura de conexão para estimar
            # Don't use opening connection's ACK to estimate
            self.handshake_complete = True
            return

        if self.estimated_rtt is None:
            self.estimated_rtt = sample_rtt
            self.dev_rtt = sample_rtt / 2
        else:
            self.estimated_rtt = (1-ALPHA) * self.estimated_rtt + ALPHA * sample_rtt
            self.dev_rtt = (1-BETA) * self.dev_rtt + BETA * abs(sample_rtt - self.estimated_rtt)

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        # Connection closing
        if (flags & FLAGS_FIN) == FLAGS_FIN:
            self.expected_seq_no += 1
            self._send_segment(
                FLAGS_ACK,
                b''
            )
            self.callback(self, b'')
            return

        # An ACK
        if (flags & FLAGS_ACK) == FLAGS_ACK:
            # A new packet has been ACKed!
            if ack_no > self.last_acked_no:
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None

                self.last_acked_no = ack_no
                # Adjusts window size with new ACK
                if self.handshake_complete:
                    self.current_window_size += 1

                # Verifica se algum dos pacotes enviados
                # ainda não foi reconhecido
                # Checks whether any sent packets
                # have not been acknowledged
                smallest_unacked_segment_idx = None
                for i, (unacked_seq_no, _, _, _) in enumerate(self.unacked_segments):
                    if unacked_seq_no > self.last_acked_no - 1:
                        smallest_unacked_segment_idx = i
                        break

                if smallest_unacked_segment_idx is None:
                    # All sent packets have been acknowledged
                    if not self.unacked_segments[-1][3]:
                        # A non-retransmitted packet has been acknowledged,
                        # RTT must be estimated again
                        self._estimate_rtt(time() - self.unacked_segments[-1][2])

                    self.unacked_segments = []
                else:
                    # There are still non-ACKED packets
                    if i > 0 and not self.unacked_segments[i-1][3]:
                        # A non-retransmitted packet has been acknowledged,
                        # RTT must be estimated again
                        self._estimate_rtt(time() - self.unacked_segments[i-1][2])

                    self.unacked_segments = self.unacked_segments[i:]
                    self.timer = asyncio.get_event_loop().call_later(self._timeout_interval(), self._resend_timer)

                # With an ACK, we can send what is in queue
                self._send_queue()

            # closing ACK
            if self.ready_to_close:
                self.server.remove_connection(self.connection_id)
                return

            # No need to ACK an empty ACK
            if len(payload) == 0:
                return

        if seq_no == self.expected_seq_no:
            self.expected_seq_no += len(payload)
            if payload != b'':
                self.callback(self, payload)

        self._send_segment(
            FLAGS_ACK,
            b'',
        )

    def _calculate_inflight_bytes(self):
        if len(self.unacked_segments) == 0:
            return 0
        else:
            return self.unacked_segments[-1][0] - self.last_acked_no + 1
    
    def _send_segment(self, flags, payload):
        """
        Adds a segment to the sending queue.
        """

        # Separates data in 1-MSS packets
        while len(payload) > MSS:
            self.sending_queue.append((self.current_seq_no, flags, payload[:MSS]))
            self.current_seq_no += MSS
            payload = payload[MSS:]

        self.sending_queue.append((self.current_seq_no, flags, payload))
        self.current_seq_no += len(payload)
        if len(payload) == 0 and ((flags & FLAGS_SYN) == FLAGS_SYN or (flags & FLAGS_FIN) == FLAGS_FIN):
            self.current_seq_no += 1
        
        # Tries to send what is in the queue
        self._send_queue()

    def _send_queue(self):
        while len(self.sending_queue) > 0 and \
            self._calculate_inflight_bytes() + len(self.sending_queue[0][2]) <= self.current_window_size * MSS:

            seq_no, flags, payload = self.sending_queue.pop(0)

            segment = make_header(
                self.connection_id[3],
                self.connection_id[1],
                seq_no,
                self.expected_seq_no,
                flags,
            )
            segment = segment + payload
            segment = fix_checksum(
                segment,
                self.connection_id[2],
                self.connection_id[0]
            )

            self.unacked_segments.append((seq_no, segment, time(), False))
            self.server.network.send(segment, self.connection_id[0])

            if self.timer is None:
                self.timer = asyncio.get_event_loop().call_later(self._timeout_interval(), self._resend_timer)

    def _resend_timer(self):
        if len(self.unacked_segments) > 0:
            # There's been a lost packet! We shall halve the window size
            self.current_window_size = max(1, self.current_window_size // 2)

            self.server.network.send(self.unacked_segments[0][1], self.connection_id[0])
            self.unacked_segments[0] = (*self.unacked_segments[0][:3], True)
        
        self.timer = asyncio.get_event_loop().call_later(self._timeout_interval(), self._resend_timer)

    # The methods below are part of the API

    def register_receiver(self, callback):
        """
        Used by the application layer to register a function to be called
        whenever data is correctly received.
        """
        self.callback = callback

    def send(self, dados):
        """
        Used by application layer to send data
        """
        self._send_segment(
            FLAGS_ACK,
            dados
        )

    def close(self):
        """
        Used by application layer to close the connection.
        """
        self.ready_to_close = True
        self._send_segment(
            FLAGS_FIN,
            b'',
        )