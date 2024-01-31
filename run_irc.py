from physical_layer.pty import PTY
from link_layer.slip import SLIP
from network_layer.ip import IP
from transport_layer.tcp import TCPServer
from application_layer.irc import IRCServer

def main():
    this_end = '192.168.123.2'
    other_end = '192.168.123.1'

    serial_line = PTY()

    link = SLIP({other_end: serial_line})

    network = IP(link)
    network.define_host_address(this_end)
    network.define_routing_table([
        ('0.0.0.0/0', other_end)
    ])

    tcp_server = TCPServer(network, 7000)

    irc_server = IRCServer(tcp_server)

    print('To connect to the other end of the physical layer, execute:')
    print('  sudo slattach -v -p slip {}'.format(serial_line.pty_name))
    print('  sudo ifconfig sl0 {} pointopoint {}'.format(other_end, this_end))
    print()
    print('Service will be available at address {}'.format(this_end))
    print()

    irc_server.run()

if __name__ == "__main__":
    main()