#!/bin/sh
set -eu
mode=$1; workdir=$2; entry=$3; shift 3

if [ "$mode" = "compile" ]; then
    # 나머지 인자(flags, --, sources)는 쓰지 않는다. entry 만 문법 검사한다.
    exec python3.9 -m py_compile "$workdir/$entry"
fi

printf '%s\n' python3.9 "$workdir/$entry"
