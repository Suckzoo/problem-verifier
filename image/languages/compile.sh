#!/bin/sh
# compile.sh <language> <workdir> <entry> <flags> -- <sources...>
set -eu
lang=$1; shift
exec "/usr/local/lib/icpc/languages/${lang}.sh" compile "$@"
