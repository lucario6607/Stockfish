.section .text.init
.globl _start
.type _start, @function

_start:
    # Set up global pointer (gp) if relaxed addressing is used
    .option push
    .option norelax
    la    gp, __global_pointer$
    .option pop

    # Set up stack pointer
    la    sp, _stack

    # Telemetry: Write 'CRT0' (0x43525430) to mailbox 0x1FF00000
    li    t0, 0x1FF00000
    li    t1, 0x43525430
    sw    t1, 0(t0)

    # Clear BSS
    la    a0, _sbss
    la    a1, _ebss
bss_clear_loop:
    bge   a0, a1, bss_done
    sw    zero, 0(a0)
    addi  a0, a0, 4
    j     bss_clear_loop
bss_done:

    # Telemetry: Write 'CRT1' (0x43525431) to mailbox 0x1FF00000
    li    t0, 0x1FF00000
    li    t1, 0x43525431
    sw    t1, 0(t0)

    # Call preinit_array constructors
    la    s0, __preinit_array_start
    la    s1, __preinit_array_end
preinit_loop:
    bge   s0, s1, preinit_done
    lw    t0, 0(s0)
    jalr  ra, t0, 0
    addi  s0, s0, 4
    j     preinit_loop
preinit_done:

    # Call init_array constructors
    la    s0, __init_array_start
    la    s1, __init_array_end
init_loop:
    bge   s0, s1, init_done
    lw    t0, 0(s0)
    li    t2, 0x1FF00004
    sw    t0, 0(t2)
    jalr  ra, t0, 0
    addi  s0, s0, 4
    j     init_loop
init_done:

    # Telemetry: Write 'CRT2' (0x43525432) to mailbox 0x1FF00000
    li    t0, 0x1FF00000
    li    t1, 0x43525432
    sw    t1, 0(t0)

    # Call main()
    call  main

hang:
    j     hang

.size _start, .-_start
