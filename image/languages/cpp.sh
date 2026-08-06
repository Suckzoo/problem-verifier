#!/bin/sh
# compile: cpp.sh compile <workdir> <entry> <flags> -- <sources...>
# run:     cpp.sh run <workdir> <entry> <memory_mib>
set -eu
mode=$1; workdir=$2; shift 3   # $3 은 entry 이며 C++ 에서는 쓰지 않는다

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-x c++ -Wall -O2 -static -pipe -std=gnu++20"
    fi
    # shellcheck disable=SC2086
    exec g++ $flags -o "$workdir/bin" "$@" -lm
fi

echo "$workdir/bin"
