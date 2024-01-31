from __future__ import annotations
from ipaddress import ip_address
import struct
from random import randint

from utils.ip import *
from utils.tcp import *

class IP:
    def __init__(self, link):
        """
        Initiate network layer. The argument is a link layer implementation
        capable of finding the next_hops.
        """
        self.callback = None
        self.link = link
        self.link.register_receiver(self.__raw_recv)
        self.ignore_checksum = self.link.ignore_checksum
        self.my_address = None
        self.identification = randint(0, 2**16 - 1)

    def __raw_recv(self, datagram):
        _, _, _, _, _, ttl, proto, \
           src_addr, dst_addr, payload = read_ipv4_header(datagram)
        if dst_addr == self.my_address:
            # acts as host
            if proto == IPPROTO_TCP and self.callback:
                self.callback(src_addr, dst_addr, payload)
        else:
            # acts as router
            next_hop = self._next_hop(dst_addr)
            new_ttl = ttl - 1
            header_size = len(datagram) - len(payload)

            if new_ttl > 0:
                datagram = bytearray(datagram)
                datagram[8:9] = struct.pack('!B', new_ttl)
                datagram[10:12] = b'\x00\x00'

                new_header = self._fix_ipv4_checksum(bytes(datagram[:header_size]))
                self.link.send(new_header + payload, next_hop)
            else:
                # Time exceeded
                icmp_header = self._assemble_icmp_header(11, 0, 0)
                return_segment = icmp_header + datagram[:(header_size + 8)]
                ipv4_header = self._assemble_ipv4_header(
                    src_addr, 
                    len(return_segment),
                    IPPROTO_ICMP,
                    64
                )
                return_hop = self._next_hop(src_addr)
                self.link.send(ipv4_header + return_segment, return_hop)

    def _next_hop(self, dest_addr):
        ip = self._ipaddr_to_bitstring(dest_addr)
        return self._routing_table.find(ip)

    def define_host_address(self, my_address):
        """
        Define this host's IPv4 address ('x.y.z.w' string). Datagrams
        sent to other addresses will be treated as if this were a router.
        """
        self.my_address = my_address

    def define_routing_table(self, table):
        """
        Define the routing table of the form
        [(cidr0, next_hop0), (cidr1, next_hop1), ...]

        where the CIDR are given in the format 'x.y.z.w/n' and
        the next_hops are given in the format 'x.y.z.w'.
        """
        self._routing_table = TRIE()
        for cidr, next_hop in table:
            self._routing_table.insert(
                self._cidr_to_bitstring(cidr),
                next_hop
            )

    def register_receiver(self, callback):
        """
        Registra uma função para ser chamada quando dados vierem da camada de rede
        """
        """
        Register a function to be called when data arrives from network layer.
        """
        self.callback = callback

    def send(self, segment, dest_addr):
        """
        Send segment to dest_addr, an IPv4 address string of the form
        'x.y.z.w'.
        """
        next_hop = self._next_hop(dest_addr)

        dest_addr = int.from_bytes(ip_address(dest_addr).packed, 'big')
        header = self._assemble_ipv4_header(
            dest_addr,
            len(segment), 
            IPPROTO_TCP,
            64
        )

        datagram = header + segment
        self.link.send(datagram, next_hop)
        self.identification = (self.identification + 1) % (2**16)

    def _cidr_to_bitstring(self, cidr):
        ip, bits = cidr.split('/')
        bits = int(bits)
        ip = int.from_bytes(ip_address(ip).packed, 'big')
        ip = f'{ip:032b}'[:bits]

        return ip 
    
    def _ipaddr_to_bitstring(self, ipaddr):
        ip = int.from_bytes(ip_address(ipaddr).packed, 'big')
        return f'{ip:032b}'
    
    def _fix_ipv4_checksum(self, header):
        header_checksum = calc_checksum(header)
        header = bytearray(header)
        header[10:12] = struct.pack('!H', header_checksum)
        return bytes(header)
    
    def _fix_icmp_checksum(self, header):
        header_checksum = calc_checksum(header)
        header = bytearray(header)
        header[2:4] = struct.pack('!H', header_checksum)
        return bytes(header)
    
    def _assemble_ipv4_header(self, dest_addr, payload_size, protocol, ttl=64):
        version__ihl = (4 << 4) + 5
        dscp__ecn = 0
        total_length = 20 + payload_size
        identification = self.identification
        flags__fragment_offset = 0
        header_checksum = 0
        src_addr = int.from_bytes(ip_address(self.my_address).packed, 'big')
        dest_addr = int.from_bytes(ip_address(dest_addr).packed, 'big')

        header = struct.pack(
            '!BBHHHBBHII',
            version__ihl,
            dscp__ecn,
            total_length,
            identification,
            flags__fragment_offset,
            ttl,
            protocol,
            header_checksum,
            src_addr,
            dest_addr
        )
        return self._fix_ipv4_checksum(header)
    
    def _assemble_icmp_header(self, type, code, rest):
        header = struct.pack(
            '!BBHI',
            type,
            code,
            0, # Checksum,
            rest,
        )
        return self._fix_icmp_checksum(header)


# TRIE implementation for routing table
class TRIE:
    _content: str | None
    _one_child: TRIE
    _zero_child: TRIE

    def __init__(self, content: str | None = None) -> None:
        self._content = content
        self._one_child = None
        self._zero_child = None

    def find(self, key: str):
        found = self._content
        found_child = None

        if len(key) > 0:
            if key[0] == '0' and self._zero_child is not None:
                found_child = self._zero_child.find(key[1:])
            elif key[0] == '1' and self._one_child is not None:
                found_child = self._one_child.find(key[1:])

        if found_child is not None:
            return found_child
        return found

    def insert(self, key: str, content: str):
        if len(key) == 0:
            self._content = content
            return
        
        if key[0] == '0':
            if self._zero_child is None:
                self._zero_child = TRIE()

            self._zero_child.insert(key[1:], content)
        elif key[0] == '1':
            if self._one_child is None:
                self._one_child = TRIE()

            self._one_child.insert(key[1:], content)