OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
    DDR (rwx) : ORIGIN = 0x1F000000, LENGTH = 15M
}

SECTIONS
{
    .text : {
        . = ALIGN(4);
        *(.text.init)
        *(.text .text.*)
        *(.rodata .rodata.*)
        *(.srodata .srodata.*)
        . = ALIGN(4);
        _etext = .;
    } > DDR

    .preinit_array : {
        . = ALIGN(4);
        PROVIDE_HIDDEN (__preinit_array_start = .);
        KEEP (*(.preinit_array))
        PROVIDE_HIDDEN (__preinit_array_end = .);
    } > DDR

    .init_array : {
        . = ALIGN(4);
        PROVIDE_HIDDEN (__init_array_start = .);
        KEEP (*(SORT_BY_INIT_PRIORITY(.init_array.*) SORT_BY_INIT_PRIORITY(.ctors.*)))
        KEEP (*(.init_array EXCLUDE_FILE (*crtbegin.o *crtbegin?.o *crtend.o *crtend?.o ) .ctors))
        PROVIDE_HIDDEN (__init_array_end = .);
    } > DDR

    .data : {
        . = ALIGN(4);
        _sdata = .;
        *(.data .data.*)
        . = ALIGN(4);
        PROVIDE( __global_pointer$ = . + 0x800 );
        *(.sdata .sdata.*)
        . = ALIGN(4);
        _edata = .;
    } > DDR

    .bss : {
        . = ALIGN(4);
        _sbss = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > DDR

    . = ALIGN(8);
    _end = .;
    __heap_start = .;
    __heap_end = 0x1F7E0000;
    _stack = 0x1FEF0000;
}
