#!/bin/sh
set -eu
mode=$1; workdir=$2; shift 3

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-x c -Wall -O2 -static -pipe -std=gnu11"
    fi
    # shellcheck disable=SC2086
    exec gcc $flags -o "$workdir/bin" "$@" -lm
fi

echo "$workdir/bin"
