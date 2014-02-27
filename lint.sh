#!/bin/sh
#set -x
iverilog -E output/axi_*.v
splint output/*_headers.h
weblint output/*html
rst2html output/*rst > /dev/null
