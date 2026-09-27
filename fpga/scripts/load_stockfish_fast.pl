#!/usr/bin/perl
use strict;
use warnings;

my $bin_file = "/tmp/stockfish_speedtest_swapped.bin";
my $bin_size = -s $bin_file;
die "Binary file not found or empty: $bin_file\n" unless $bin_size && $bin_size > 0;

print "Loading $bin_size bytes of byte-swapped Stockfish into DDR3 at 0x1F000000...\n";

my $SYS_read = 3;
my $SYS_mmap2 = 192;
my $SYS_munmap = 91;

open(my $fmem, "+<", "/dev/mem") or die "Cannot open /dev/mem: $!\n";
my $fd_mem = fileno($fmem);

# 1. Map 16MB starting at physical 0x1F000000 for Stockfish binary
my $map_len = 16 * 1024 * 1024;
my $pgoff = 0x1f000000 >> 12;

my $ptr = syscall($SYS_mmap2, 0, $map_len, 3, 1, $fd_mem, $pgoff);
if ($ptr == -1 || $ptr == 0) {
    die "mmap2 failed!\n";
}

# Open binary
open(my $fbin, "<", $bin_file) or die "Cannot open $bin_file: $!\n";
my $fd_bin = fileno($fbin);

# Read entire binary directly into physical DDR3 via kernel SYS_read
my $total = 0;
while ($total < $bin_size) {
    my $to_read = $bin_size - $total;
    $to_read = 1024 * 1024 if $to_read > 1024 * 1024;
    my $n = syscall($SYS_read, $fd_bin, $ptr + $total, $to_read);
    die "SYS_read error at offset $total\n" if !defined($n) || $n <= 0;
    $total += $n;
}
close($fbin);
printf("Successfully loaded %d bytes into 0x1F000000!\n", $total);
syscall($SYS_munmap, $ptr, $map_len);

# 2. Write Trampoline at 0x10000000 (SPARC AHB 0x40000000) via devmem with SP init
system("/sbin/devmem 0x10000000 32 0x1d13fc00"); # sethi %hi(0x4ff00000), %sp
system("/sbin/devmem 0x10000004 32 0x0313c000"); # sethi %hi(0x4f000000), %g1
system("/sbin/devmem 0x10000008 32 0x81c04000"); # jmp %g1
system("/sbin/devmem 0x1000000c 32 0x01000000"); # nop

# 3. Clear Mailbox at physical 0x1FF00000
for (my $i = 0; $i < 8; $i++) {
    my $a = 0x1ff00000 + $i * 4;
    system(sprintf("/sbin/devmem 0x%08x 32 0x00000000", $a));
}

close($fmem);
print "LOAD_AND_TRAMPOLINE_COMPLETE\n";
