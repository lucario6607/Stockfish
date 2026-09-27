# Stockfish on FPGA (Zynq-7010: MicroBlaze-V, LEON3 SPARC, ARM Cortex-A9)

This branch contains the bare-metal port of the Stockfish chess engine tailored for FPGA execution on Xilinx Zynq-7000 SoC (specifically tested on the Antminer S9 control board featuring a Zynq-7010 XC7Z010 FPGA and dual ARM Cortex-A9 cores), along with the custom AXI hardware neural network (NNUE) accelerator.

---

## 1. Executive Summary & Benchmark Results

- **Official Benchmark Run:** Standard 258-position Stockfish suite (`benchmark "1 1 150"`: 1 thread, 1 MB TT, 150 s scaled).
- **Peak Hardware Performance:** Bare-Metal MicroBlaze-V RV32 @ 100 MHz + 16-lane DSP48E1 HW NNUE Accelerator.
- **Positions Evaluated:** **258 / 258**
- **Total Chess Nodes Searched:** **186,245 nodes**
- **Hardware Elapsed Search Time:** **99,879 ms (~99.88 s)**
- **Achieved Search Speed:** **1,864 NPS** (**+24.3% over the 1,500 NPS baseline**)
- **Hardware Status:** `0x444F4E45` ('DONE') with 0 traps / exceptions, active HW acceleration tag `0xACC100FF` across all positions.

---

## 2. All Architectures & Execution Environments Evaluated

Across the progression of this project, multiple embedded and softcore architectures were synthesized, configured, and benchmarked on the physical Antminer S9 platform:

### Architecture 1: Native Dual ARM Cortex-A9 (Zynq-7000 PS @ 667 MHz)
- **Role:** Processing System (PS) baseline and host orchestrator.
- **Execution Environment:** 32-bit ARMv7-A running embedded Busybox Linux.
- **Role in Stack:** Managed kernel failsafes, network daemons (DHCP/HTTP), bitstream flashing via `/dev/xdevcfg`, level shifters via SLCR, high-speed DMA loading into DDR3 via `/dev/mem`, and telemetry polling.
- **Characteristics:** Provides strong general integer performance (~15,000+ NPS) but lacks dedicated FPGA DSP co-processing for matrix dot products. Used as the supervisory controller for all bare-metal PL cores.

### Architecture 2: GRLIB LEON3 SPARC V8 Softcore (Stages 1–4, PL @ 82.36 MHz)
- **Design:** Synthesized single-issue 7-stage LEON3 SPARC V8 core with GRLIB AMBA-2.0 AHB/APB interconnect.
- **Toolchain:** Cobham Gaisler BCC 2.3.1 (`sparc-gaisler-elf-g++` GCC 13.2.1) cross-compiler targeting C++17 bare-metal.
- **Evolution across Stages:**
  - **Stage 1 (Baseline Pure CPU):** Achieved **395.2 NPS** running pure software NNUE on `nn-61e7af4bb97d.nnue` (1.1 MB net) with deterministic clock emulation.
  - **Stage 2 (AHB/DDR3 Cache & Bus Tuning):** Optimized AXI-to-AHB bridge memory windows, reducing DDR3 read stall latency.
  - **Stage 3 & 4 (Custom APB NNUE Accelerator):** Designed and integrated custom APB NNUE coprocessor (`fpga/rtl/nnue_accel_apb.vhd`), reaching **1,138.4 NPS**.
- **Limitations Identified:**
  - SPARC V8 fixed register window spill/fill traps (`save`/`restore`) incurred heavy branch and memory penalties during deep alpha-beta search tree recursion.
  - Frequency ceiling capped at ~82.36 MHz on the Speed Grade -1 Zynq-7010 fabric.
  - Big-endian byte swapping overhead when transferring binary weights and bitboards from host.

### Architecture 3: MicroBlaze-V RV32 Softcore (Stage 5 Single-Core Baseline @ 100.00 MHz)
- **Design:** AMD/Xilinx Vivado MicroBlaze-V core implementing the open RISC-V 32-bit ISA:
  `RV32IM_Zba_Zbb_Zbs_Zicbom_Zicsr_Zifencei`.
- **Clock:** **100.00 MHz** (`fclk0` driven from Zynq PS PLL via SLCR divisor 10).
- **Interconnect:** AXI4 interconnect connecting the RV32 core to PS HP0 (64-bit DDR3 access) and `M_AXI_DP` for memory-mapped peripherals.
- **Initial Performance:** Achieved **1,052 NPS** without vector memory packing.
- **Advantages over SPARC:**
  - Standard flat register file (32 general-purpose registers) with zero window-spill traps.
  - Native little-endian format matches host x86 and standard NNUE weight quantization layouts.
  - Hardware CSRs (`mcycle` / `mcycleh`) allow 1-cycle latency timekeeping without peripheral bus polling.

### Architecture 4: MicroBlaze-V RV32 + 16-Lane DSP48E1 HW Accelerator + 32-bit Memory Packing (Stage 5 Optimized) [Current Record: 1,864 NPS]
- **Design:** Single-core MicroBlaze-V RV32 core coupled to a custom 16-lane DSP48E1 parallel MAC coprocessor on AXI4-Lite (`0x40000000`).
- **Optimizations Applied:**
  1. **32-Bit Word Packing in Accumulator:** Vectorized 16-bit weight addition in `nnue_accumulator.cpp` to use 32-bit `lw`/`sw`, cutting DDR3 bus transactions by 50%.
  2. **Relocated Transposition Table (TT):** Moved 1 MB TT from `0x1F400000` to `0x1F800000` in `tt.cpp`, preventing collision with the 1.88 MB NNUE evaluation heap.
  3. **Single-Cycle TT Hash Indexing:** Replaced 128-bit `mul_hi64` math with single-cycle power-of-two shift logic on RV32.
  4. **Non-Ratified Instruction Removal:** Cleaned out non-standard `pack`/`packh` inline asm hazards in feature transformers, replacing with ratified 32-bit bitops.
  5. **Direct Hardware Timer:** Switched time tracking from unresponsive AXI Timer to CPU CSR `mcycle`.
- **Result:** Successfully reached **1,864 NPS** across the full 258-position suite (**+24.3% over the 1,500 NPS baseline**).

### Architecture 5: Dual-Core MicroBlaze-V RV32 SMP Fabric (Exploratory / Synthesis Study)
- **Design Topology:** Dual RV32IM_Zba_Zbb_Zbs cores (`Hart 0` on HP0, `Hart 1` on HP1) sharing `axi_timer_0` and the 16-lane NNUE accelerator via an expanded 2-SI AXI crossbar.
- **Resource Feasibility on Zynq-7010 (17,600 LUTs, 60 BRAMs, 80 DSPs):**
  - Slice LUTs: 14,564 / 17,600 (82.7% utilization).
  - BRAM36: 49 / 60 (81.7% utilization).
  - DSP48E1: 29 / 80 (36.3% utilization).
- **Target Projection:** 3,000–4,000 NPS with 2-thread Stockfish SMP search.

---

## 3. Performance Summary Table Across Architectures

| Stage / Architecture | ISA | Frequency | Acceleration | 258-Pos Search NPS | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 1: LEON3 Baseline** | SPARC V8 | 82.36 MHz | Software (Pure CPU) | **395.2 NPS** | Register window spill overhead |
| **Stage 4: LEON3 Optimized** | SPARC V8 | 82.36 MHz | APB NNUE Accel | **1,138.4 NPS** | Custom APB HW coprocessor |
| **Stage 5: MicroBlaze-V Base**| RISC-V RV32 | 100.00 MHz | 16-Lane DSP48E1 AXI | **1,052.0 NPS** | Scalar accumulator memory access |
| **Stage 5: MicroBlaze-V Opt** | RISC-V RV32 | 100.00 MHz | 16-Lane DSP48E1 AXI | **1,542.0 NPS** | 32-bit word memory packing |
| **Stage 5: MicroBlaze-V Peak**| RISC-V RV32 | 100.00 MHz | 16-Lane DSP48E1 AXI | **1,864.0 NPS** | TT relocation + CSR mcycle + LTO |
| **Projected: Dual MicroBlaze**| Dual RV32 | 125.00 MHz | Shared 16-Lane DSP | *~3,500 NPS* | Pipelined squarer + 2-thread SMP |

---

## 4. Hardware Architecture & Acceleration Details

### 16-Lane DSP48E1 NNUE Accelerator (`fpga/rtl/nnue_accel_axi.vhd`)
- **Base Address:** `0x40000000` (mapped in AXI address space).
- **Execution Mechanism:**
  - 16 parallel DSP48E1 MAC units evaluating feature transformer / FC layer activations.
  - On-chip dual-port block RAMs for feature accumulators (`feat_ram`: 256×32) and weights (`fc0_ram_0` through `fc0_ram_7`: 8 banks of 1024×32, 32 KB total).
  - Offloads the computationally heavy half-KP / half-KA feature vector dot-products from the RISC-V CPU core.
  - Active detection tag: `0xACC100FF`.

### Memory Layout & Linker Strategy (`fpga/sw/riscv_ddr.ld`)
The Zynq-7010 shares 512 MB DDR3 between PS (ARM Linux) and PL (MicroBlaze-V):
- `0x1F000000 - 0x1F36F9C7`: Stockfish text, rodata, and data (.text entry at `0x1F000000`).
- `0x1F36F9C8 - 0x1F7DFFFF`: Dynamic Heap (`_sbrk`), sizing ~4.5 MB (strictly isolates NNUE evaluation structures).
- `0x1F800000 - 0x1F8FFFFF`: 1 MB Transposition Table (TT) (relocated away from `0x1F400000` to prevent heap collision).
- `0x1FEF0000`: Top of Stack (`_stack`), growing downward.
- `0x1FF00000`: Hardware Telemetry Mailbox (32 words of shared non-cached registers).

---

## 5. Hardware Telemetry Mailbox Protocol (`0x1FF00000`)

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

## 6. Repository Structure

```
.
├── README_FPGA.md                 # Full documentation of all architectures, benchmark, memory map & telemetry
├── fpga/
│   ├── rtl/
│   │   ├── nnue_accel_axi.vhd     # 16-Lane DSP48E1 AXI4-Lite hardware coprocessor for MicroBlaze-V
│   │   └── nnue_accel_apb.vhd     # AMBA APB hardware coprocessor for LEON3 SPARC V8
│   ├── sw/
│   │   ├── crt0_riscv.S           # Bare-metal startup, BSS clear, constructor calls, telemetry beacons
│   │   ├── syscalls_riscv.c       # Minimal newlib stubs (_sbrk, _write, _read, _getentropy)
│   │   ├── riscv_ddr.ld           # Linker script with safe heap ceilings & TT memory isolation
│   │   └── build_stockfish_riscv.py # Standalone RISC-V GCC/G++ build & flat binary generator
│   └── scripts/
│       ├── run_speedtest_stage5.py # Automated host orchestrator: reset control, DMA loader, telemetry polling
│       ├── run_speedtest_stage3.py # Runner for Stage 3/4 LEON3 SPARC bitstream
│       ├── persistent_dhcp.py     # Dual-socket DHCP server for Antminer direct ethernet
│       ├── do_exploit.py          # Root telnet exploit recovery via upload_conf.cgi
│       ├── load_stockfish_riscv.pl # Target Perl DMA memory loader for 0x1F000000 (RISC-V)
│       ├── load_stockfish_fast.pl  # Target Perl DMA memory loader for 0x1F000000 (SPARC byte-swapped)
│       └── read_mb.pl             # Low-overhead mmap mailbox reader
└── src/                           # Complete Stockfish engine source with bare-metal FPGA patches
    ├── baremetal.h                # Single-threaded atomic overrides and memory macros
    ├── main.cpp                   # Bare-metal entry point and stage telemetry beacons
    ├── uci.cpp                    # Real-time hardware mailbox updates per search position
    ├── misc.h                     # 1-cycle CSR mcycle/mcycleh hardware timekeeping
    ├── tt.cpp                     # Transposition Table relocated to 0x1F800000 (heap collision fix)
    └── nnue/                      # Ratified 32-bit operations (pack/packh hazard elimination)
```

---

## 7. How to Build & Run

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
