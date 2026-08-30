#!/usr/bin/env perl

# Basics: are there semantic errors which are easy to spot?

use strict;
use Test::More;

my $tests = 0;
my $prg="testssl.sh";
my $os="$^O";

if ( $os eq "darwin" ){
     plan skip_all => 'No checks on MacOS';
}

#1
printf "\n%s\n", "Testing for missing vars at left hand side in double square brackets ...";

# I know this isn't nice but perl doesn't seem for this so great either
my @matches = `grep -n '\\[\\[ [[:alpha:]]' $prg`;
is(scalar(@matches), 0, "Checking bad '[[ LHS' patterns")
    or diag(@matches);
$tests++;

# The following works only on GNU grep

#2
printf "\n%s\n", "Testing for backticks ...";

my @matches = qx(grep -nP '`[^`]*`' $prg);
is(scalar(@matches), 0, "Checking bad backtick patterns")
or diag(@matches);
$tests++;

#3
printf "\n%s\n", "Sourcing without checking the file exists #1 ...";

my @matches = qx(grep -nP '^\s*\.\s+\$' $prg);
is(scalar(@matches), 0, "Checking bad sourcing pattern #1")
or diag(@matches);
$tests++;

#4
printf "\n%s\n", "Sourcing without checking the file exists #2 ...";

my @matches = qx(grep -nP '^\s*source\s+\$' $prg);
is(scalar(@matches), 0, "Checking bad sourcing pattern #2")
or diag(@matches);
$tests++;


# We have three eval already, a) re-analyse + exempt them
#my @matches = qx(grep -nP '\beval\b' $prg);


# more would go here

printf "\n";
done_testing($tests);


#  vim:ts=5:sw=5:expandtab

