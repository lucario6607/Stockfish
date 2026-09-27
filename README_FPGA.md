# Stockfish on FPGA (Zynq-7010 & MicroBlaze-V RV32)

This branch contains the bare-metal port of the Stockfish chess engine tailored for FPGA execution on Xilinx Zynq-7000 SoC (specifically tested on the Antminer S9 control board featuring a Zynq-7010 XC7Z010 FPGA and dual ARM Cortex-A9 cores), along with the custom AXI hardware neural network (NNUE) accelerator.

---

## 1. Executive Summary & Benchmark Results

- **Official Benchmark Run:** Standard 258-position Stockfish suite (`benchmark "1 1 150"`: 1 thread, 1 MB TT, 150 s scaled).
- **Core Architecture:** Bare-Metal MicroBlaze-V RV32IM_Zba_Zbb_Zbs_Zicbom_Zicsr_Zifencei @ 100 MHz (`fclk0`).
- **Hardware Acceleration:** 16-Lane DSP48E1 Parallel MAC NNUE Accelerator on AXI4-Lite (`0x40000000`).
- **Positions Evaluated:** **258 / 258**
- **Total Chess Nodes Searched:** **186,245 nodes**
- **Hardware Elapsed Search Time:** **99,879 ms (~99.88 s)**
- **Achieved Search Speed:** **1,864 NPS** (**+24.3% over the 1,500 NPS baseline**)
- **Hardware Status:** `0x444F4E45` ('DONE') with 0 traps / exceptions, active HW acceleration tag `0xACC100FF` across all positions.

---

## 2. Architectures & Optimization Approaches Explored

Throughout this project, multiple embedded and softcore architectures were analyzed, synthesized, and benchmarked on the physical Zynq-7010 PL:

### Architecture 1: SPARC V8 (GRLIB LEON3)
- **Design:** Synthesized single-issue 7-stage LEON3 SPARC V8 core with GRLIB AMBA-2.0 AHB/APB interconnect.
- **Clock:** ~82.36 MHz.
- **Evaluation:**
  - Provided clean open-source RTL and bare-metal BCC toolchain.
  - Custom APB NNUE accelerator was designed (`fpga/rtl/nnue_accel_apb.vhd`).
  - Limitations: Register window overhead on deep recursion in chess alpha-beta tree search, and toolchain constraints with modern C++17/C++20 Stockfish constructs.

### Architecture 2: MicroBlaze-V (RISC-V RV32IMA)
- **Design:** AMD/Xilinx Vivado MicroBlaze-V core implementing the open RISC-V 32-bit ISA with Integer Multiply/Divide (M), Address Generation (Zba), Basic Bit-manipulation (Zbb), Single-bit operations (Zbs), and Cache/CSR management (Zicbom, Zicsr, Zifencei).
- **Clock:** **100.00 MHz** (`fclk0` from Zynq PS SLCR).
- **Interconnect:** AXI4 interconnect connecting the RV32 core, high-speed DDR3 memory window via Zynq HP/GP AXI ports, and memory-mapped custom peripherals.
- **Evaluation:**
  - Superior compiler optimizations from modern GCC/Clang with standard RV32 calling conventions.
  - Direct hardware cycle counting via RISC-V CSRs (`mcycle` / `mcycleh`) with 1-cycle latency and zero bus penalty.
  - Allowed seamless integration of custom 16-lane DSP48E1 coprocessor on AXI.

---

## 3. Hardware Architecture & Acceleration

### 16-Lane DSP48E1 NNUE Accelerator (`fpga/rtl/nnue_accel_axi.vhd`)
- **Base Address:** `0x40000000` (mapped in AXI address space).
- **Execution Mechanism:**
  - 16 parallel DSP48E1 MAC units evaluating feature transformer / FC layer activations.
  - On-chip dual-port block RAMs for feature accumulators (`feat_ram`: 256×32) and weights (`fc0_ram_0` through `fc0_ram_7`: 8 banks of 1024×32, 32 KB total).
  - Offloads the computationally heavy half-KP / half-KA feature vector dot-products from the RISC-V CPU core.
  - Active detection tag: `0xACC100FF`.

### Memory Layout & Linker Strategy (`fpga/sw/riscv_ddr.ld`)
The Zynq-7010 shares 512 MB DDR3 between PS (ARM Linux) and PL (MicroBlaze-V). To avoid memory contention and corruption:
- `0x1F000000 - 0x1F36F9C7`: Stockfish text, rodata, and data (.text entry at `0x1F000000`).
- `0x1F36F9C8 - 0x1F7DFFFF`: Dynamic Heap (`_sbrk`), sizing ~4.5 MB (strictly isolates NNUE evaluation structures).
- `0x1F800000 - 0x1F8FFFFF`: 1 MB Transposition Table (TT) (relocated away from `0x1F400000` to prevent heap collision).
- `0x1FEF0000`: Top of Stack (`_stack`), growing downward.
- `0x1FF00000`: Hardware Telemetry Mailbox (32 words of shared non-cached registers).

---

## 4. Hardware Telemetry Mailbox Protocol (`0x1FF00000`)

The RISC-V core communicates real-time progress to the host ARM Cortex-A9 via the hardware mailbox:

| Offset | Register Name | State During Search (`0x53504544`) | State at Completion (`0x444F4E45`) |
| :--- | :--- | :--- | :--- |
| `+0x00` | **Status / Magic** | `0x53504544` ('SPED' = speedtest running) | `0x444F4E45` ('DONE' = finished) |
| `+0x04` | **Current Position**| Index `1..258` | Final position count (`258`) |
| `+0x08` | **Total Positions** | Total benchmark count (`258`) | Total benchmark count (`258`) |
| `+0x0C` | **Nodes (Low 32)**  | Search nodes `[31:0]` | Final search nodes `[31:0]` |
| `+0x10` | **Nodes (High 32)** | Search nodes `[63:32]` | Final search nodes `[63:32]` |
| `+0x14` | **Elapsed Time (ms)**| Hardware timer (CSR `mcycle`) elapsed ms | Final elapsed ms |
| `+0x18` | **NPS**             | Current Nodes Per Second | Final true NPS (`1,864`) |
| `+0x1C` | **Accelerator Tag** | `0xACC100FF` (HW DSP active) | Heartbeat counter |

---

## 5. Repository Structure

```
.
├── fpga/
│   ├── rtl/
│   │   ├── nnue_accel_axi.vhd       # 16-Lane DSP48E1 AXI4-Lite NNUE coprocessor (MicroBlaze-V)
│   │   └── nnue_accel_apb.vhd       # AMBA APB NNUE coprocessor (LEON3 SPARC V8)
│   ├── sw/
│   │   ├── crt0_riscv.S             # Bare-metal startup, BSS clear, constructor calls, telemetry
│   │   ├── syscalls_riscv.c         # Minimal newlib stubs (_sbrk, _write, _read, _getentropy)
│   │   ├── riscv_ddr.ld             # Linker script with isolated memory map & TT boundary
│   │   └── build_stockfish_riscv.py # Bare-metal RV32 compilation & binary extraction script
│   └── scripts/
│       ├── run_speedtest_stage5.py  # Host orchestrator: reset release, DMA load, mailbox polling
│       ├── persistent_dhcp.py       # Dual-socket DHCP daemon for Antminer direct ethernet
│       ├── do_exploit.py            # Telnet auto-exploit recovery for Antminer Linux
│       ├── load_stockfish_riscv.pl  # Embedded Perl kernel DMA loader into DDR3 (0x1F000000)
│       └── read_mb.pl               # Low-overhead mmap mailbox reader
└── src/                             # Stockfish C++ engine source with bare-metal patches
    ├── baremetal.h                  # Bare-metal definitions, atomic stubs, memory overrides
    ├── main.cpp                     # Bare-metal entry point & stage telemetry beacons
    ├── uci.cpp                      # Benchmark harness with live mailbox telemetry per position
    ├── misc.h                       # 1-cycle CSR mcycle/mcycleh hardware timekeeping
    ├── tt.cpp                       # Fixed TT pointer relocation to 0x1F800000
    └── nnue/                        # Ratified 32-bit bitops (pack/packh hazard elimination)
```

---

## 6. How to Build & Run

### Building the Bare-Metal RISC-V Stockfish Binary:
```bash
python fpga/sw/build_stockfish_riscv.py
```
This generates `stockfish_riscv.bin` (~2.4 MB flat binary).

### Running on Physical Hardware (Antminer S9 / Zynq-7010):
1. Connect host PC to S9 Ethernet port (`192.168.2.1`).
2. Start background DHCP & HTTP servers:
   ```bash
   python fpga/scripts/persistent_dhcp.py &
   python -m http.server 8000 --bind 192.168.2.1 &
   ```
3. Execute the automated speedtest orchestrator:
   ```bash
   python fpga/scripts/run_speedtest_stage5.py --skip-prog
   ```
   *(Omit `--skip-prog` if the FPGA bitstream needs to be loaded into the PL).*
