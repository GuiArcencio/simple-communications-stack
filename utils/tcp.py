import struct

FLAGS_FIN = 1<<0
FLAGS_SYN = 1<<1
FLAGS_RST = 1<<2
FLAGS_ACK = 1<<4

MSS = 1460   # Payload size for a TCP segment (in bytes)

def make_header(src_port, dst_port, seq_no, ack_no, flags):
    """
    Construct a simplified TCP header.
    """
    return struct.pack(
        '!HHIIHHHH',
        src_port, dst_port,
        seq_no, ack_no, 
        (5 << 12) | flags,
        8*MSS, 0, 0
    )


def read_header(segment):
    """
    Reads a TCP header.
    """
    src_port, dst_port, seq_no, ack_no, \
        flags, window_size, checksum, urg_ptr = \
        struct.unpack('!HHIIHHHH', segment[:20])
    
    return src_port, dst_port, seq_no, ack_no, \
        flags, window_size, checksum, urg_ptr


def calc_checksum(segment, src_addr=None, dst_addr=None):
    """
    Calculate one's complement checksum for given data.

    IPv4 addresses must be passed as 'x.y.z.w' strings
    """
    if src_addr is None and dst_addr is None:
        data = segment
    else:
        pseudohdr = str2addr(src_addr) + str2addr(dst_addr) + \
            struct.pack('!HH', 0x0006, len(segment))
        data = pseudohdr + segment

    if len(data) % 2 == 1:
        # if odd, padds to the right
        data += b'\x00'
    
    checksum = 0
    for i in range(0, len(data), 2):
        x, = struct.unpack('!H', data[i:i+2])
        checksum += x
        while checksum > 0xffff:
            checksum = (checksum & 0xffff) + 1
    checksum = ~checksum
    return checksum & 0xffff


def fix_checksum(segment, src_addr, dst_addr):
    """
    Fix the checksum of a TCP segment.
    """
    seg = bytearray(segment)
    seg[16:18] = b'\x00\x00'
    seg[16:18] = struct.pack('!H', calc_checksum(seg, src_addr, dst_addr))

    return bytes(seg)


def addr2str(addr):
    """
    Convert a binary IPv4 to a 'x.y.z.w' string
    """
    return '%d.%d.%d.%d' % tuple(int(x) for x in addr)


def str2addr(addr):
    """
    Convert a 'x.y.z.w' to a binary IPv4.
    """
    return bytes(int(x) for x in addr.split('.'))