#!/bin/sh
set -eu
mode=$1; workdir=$2; entry=$3; shift 3

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-encoding UTF-8"
    fi
    # shellcheck disable=SC2086
    exec javac $flags -sourcepath "$workdir" -d "$workdir" "$@"
fi

memory_mib=$1
heap=$((memory_mib - 256))
if [ "$heap" -lt 256 ]; then heap=256; fi
printf '%s\n' java -Xrs -XX:+UseSerialGC -Xss64m "-Xmx${heap}m" -cp "$workdir" "$entry"
