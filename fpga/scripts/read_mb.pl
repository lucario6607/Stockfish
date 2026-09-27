#!/usr/bin/perl
use strict;
use warnings;

open(my $f, "+<", "/dev/mem") or die $!;
my $ptr = syscall(192, 0, 4096, 3, 1, fileno($f), 0x1ff00);
if ($ptr == -1 || $ptr == 0) {
    die "mmap failed: $!\n";
}
my @v;
for my $i (0..7) {
    my $p = pack("L", $ptr + $i * 4);
    my $raw = unpack("P4", $p);
    push @v, unpack("V", $raw);
}
print join(" ", @v), "\n";
