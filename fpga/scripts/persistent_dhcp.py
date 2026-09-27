import socket
import struct
import select
import time

SERVER_IP = '192.168.2.1'
OFFER_IP = '192.168.2.100'
NETMASK = '255.255.255.0'
BROADCAST_IP = '255.255.255.255'

sockets = []

# Socket 1: Bound to interface IP
try:
    s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s1.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s1.bind((SERVER_IP, 67))
    sockets.append(s1)
    print("Bound socket 1 to 192.168.2.1:67", flush=True)
except Exception as e:
    print(f"Error binding 192.168.2.1:67: {e}", flush=True)

# Socket 2: Bound to INADDR_ANY
try:
    s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s2.bind(('', 67))
    sockets.append(s2)
    print("Bound socket 2 to 0.0.0.0:67", flush=True)
except Exception as e:
    print(f"Error binding 0.0.0.0:67: {e}", flush=True)

print("Persistent Dual DHCP server running for Antminer...", flush=True)

while True:
    r, _, _ = select.select(sockets, [], [], 1.0)
    for sock in r:
        try:
            data, addr = sock.recvfrom(2048)
        except Exception:
            continue

        if len(data) < 240:
            continue

        xid = data[4:8]
        chaddr = data[28:34]
        magic_cookie = data[236:240]

        if magic_cookie != b'\x63\x82\x53\x63':
            continue

        options = data[240:]
        msg_type = None
        i = 0
        while i < len(options):
            opt = options[i]
            if opt == 255:
                break
            if opt == 0:
                i += 1
                continue
            if i + 1 >= len(options):
                break
            opt_len = options[i+1]
            opt_val = options[i+2:i+2+opt_len]
            if opt == 53 and opt_len > 0:
                msg_type = opt_val[0]
            i += 2 + opt_len

        mac_str = ':'.join(f'{b:02x}' for b in chaddr)
        print(f"Incoming DHCP request type {msg_type} from {mac_str}", flush=True)
        if not mac_str.startswith('34:c3:40'):
            continue

        offer_ip_b = socket.inet_aton(OFFER_IP)
        server_ip_b = socket.inet_aton(SERVER_IP)
        netmask_b = socket.inet_aton(NETMASK)

        resp_type = None
        if msg_type == 1:
            resp_type = 2
            print(f"DHCP OFFER: {OFFER_IP} to {mac_str}", flush=True)
        elif msg_type == 3:
            resp_type = 5
            print(f"DHCP ACK: {OFFER_IP} to {mac_str}", flush=True)

        if resp_type:
            packet = bytearray(300)
            packet[0] = 2
            packet[1] = 1
            packet[2] = 6
            packet[3] = 0
            packet[4:8] = xid
            packet[8:10] = b'\x00\x00'
            packet[10:12] = b'\x80\x00'
            packet[12:16] = b'\x00\x00\x00\x00'
            packet[16:20] = offer_ip_b
            packet[20:24] = server_ip_b
            packet[24:28] = b'\x00\x00\x00\x00'
            packet[28:34] = chaddr
            packet[236:240] = b'\x63\x82\x53\x63'

            opts = bytearray()
            opts += bytes([53, 1, resp_type])
            opts += bytes([54, 4]) + server_ip_b
            opts += bytes([51, 4, 0, 1, 81, 128]) # 24 hour lease
            opts += bytes([1, 4]) + netmask_b
            opts += bytes([3, 4]) + server_ip_b
            opts += bytes([6, 4]) + server_ip_b
            opts += bytes([255])

            packet = bytes(packet[:240]) + bytes(opts)
            for target in [BROADCAST_IP, '192.168.2.255']:
                for s_out in sockets:
                    try:
                        s_out.sendto(packet, (target, 68))
                    except Exception:
                        pass
