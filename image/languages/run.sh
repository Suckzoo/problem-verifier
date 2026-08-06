#!/bin/sh
# run.sh <language> <workdir> <entry> <memory_mib>
# 실행 argv 를 한 줄에 하나씩 stdout 에 출력한다.
set -eu
lang=$1; shift
exec "/usr/local/lib/icpc/languages/${lang}.sh" run "$@"
