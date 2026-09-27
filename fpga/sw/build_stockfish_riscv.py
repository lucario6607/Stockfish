import subprocess, os, sys

gxx = r'C:\Xilinx\2026.1\gnu\riscv\nt\bin\riscv64-unknown-elf-g++.exe'
gcc = r'C:\Xilinx\2026.1\gnu\riscv\nt\bin\riscv64-unknown-elf-gcc.exe'
objcopy = r'C:\Xilinx\2026.1\gnu\riscv\nt\bin\riscv64-unknown-elf-objcopy.exe'
src_dir = r'C:\Users\Kolby\.gemini\antigravity\scratch\sparc_zynq\sf_1mb\Stockfish-7e86010f66e00b913d8da5a3c8665da4faf1cb05\src'
baremetal = os.path.join(src_dir, 'baremetal.h')

scratch_dir = r'C:\Users\Kolby\.gemini\antigravity\brain\94c22eb8-ee9b-4c78-b41b-a26adc60c88c\scratch'
crt0_src = os.path.join(scratch_dir, 'crt0_riscv.S')
crt0_obj = os.path.join(scratch_dir, 'crt0_riscv.o')
syscalls_src = os.path.join(scratch_dir, 'syscalls_riscv.c')
syscalls_obj = os.path.join(scratch_dir, 'syscalls_riscv.o')
ld_script = r'C:\Users\Kolby\.gemini\antigravity\scratch\sparc_zynq\riscv_ddr.ld'

# 1. Compile crt0 and syscalls
print("Compiling crt0 and syscalls...")
subprocess.run([gcc, '-march=rv32im_zba_zbb_zbs_zicsr_zifencei', '-mabi=ilp32', '-c', crt0_src, '-o', crt0_obj], check=True)
subprocess.run([gcc, '-march=rv32im_zba_zbb_zbs_zicsr_zifencei', '-mabi=ilp32', '-O3', '-c', syscalls_src, '-o', syscalls_obj], check=True)

sources = [
    'attacks.cpp',
    'benchmark.cpp',
    'bitboard.cpp',
    'engine.cpp',
    'evaluate.cpp',
    'main.cpp',
    'memory.cpp',
    'misc.cpp',
    'movegen.cpp',
    'movepick.cpp',
    'nnue/features/p_hm.cpp',
    'nnue/network.cpp',
    'nnue/nnue_accumulator.cpp',
    'nnue/nnue_misc.cpp',
    'position.cpp',
    'score.cpp',
    'search.cpp',
    'syzygy/tbprobe.cpp',
    'thread.cpp',
    'timeman.cpp',
    'tt.cpp',
    'tune.cpp',
    'uci.cpp',
    'ucioption.cpp',
    'posix_stubs.cpp'
]

cflags = [
    '-march=rv32im_zba_zbb_zbs_zicbom_zicsr_zifencei', '-mabi=ilp32',
    '-O3', '-flto', '-fomit-frame-pointer', '-finline-functions',
    '-fno-rtti', '-fno-exceptions',
    '-mbranch-cost=1',
    '-falign-functions=16',
    '-falign-loops=16',
    '-std=c++17', '-DNDEBUG', '-DNO_NUMA',
    '-DBAREMETAL_RISCV', '-DUSE_SLOPPY_ATOMICS',
    '-include', baremetal, '-I' + src_dir
]

objs = [crt0_obj, syscalls_obj]
for src in sources:
    obj_name = src.replace('/', '_').replace('\\', '_').replace('.cpp', '_riscv.o')
    obj_path = os.path.join(src_dir, obj_name)
    src_path = os.path.join(src_dir, src)
    objs.append(obj_path)
    
    if os.path.exists(obj_path) and os.path.getmtime(obj_path) > os.path.getmtime(src_path):
        print(f"Skipping {src} (up to date)")
        continue
    
    print(f"Compiling {src}...")
    cmd = [gxx] + cflags + ['-c', src_path, '-o', obj_path]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=src_dir)
    if res.returncode != 0:
        print(f"ERROR compiling {src}:")
        print(res.stderr)
        sys.exit(1)

print("All objects compiled successfully!")

elf_path = os.path.join(src_dir, 'stockfish_riscv.elf')
print(f"Linking {elf_path}...")

link_cmd = [
    gxx, '-march=rv32im_zba_zbb_zbs_zicbom_zicsr_zifencei', '-mabi=ilp32', '-O3', '-flto',
    '-nostartfiles',
    '-Wl,--build-id=none',
    '-T', ld_script,
] + objs + ['-o', elf_path]

res = subprocess.run(link_cmd, capture_output=True, text=True, cwd=src_dir)
if res.returncode != 0:
    print('LINK FAILED:')
    print(res.stderr)
    sys.exit(1)

print('Linked successfully!')

bin_path = os.path.join(src_dir, 'stockfish_riscv.bin')
print(f'Creating binary {bin_path}...')
subprocess.run([objcopy, '-O', 'binary', elf_path, bin_path], check=True)
bin_size = os.path.getsize(bin_path)
print(f'Raw binary size: {bin_size:,} bytes')

# Copy to host web root for HTTP delivery to S9
target_bin = r'C:\Users\Kolby\.gemini\antigravity\scratch\sparc_zynq\stockfish_riscv.bin'
with open(bin_path, 'rb') as f_in, open(target_bin, 'wb') as f_out:
    f_out.write(f_in.read())

print(f'Copied binary to {target_bin}! Ready for board delivery!')
