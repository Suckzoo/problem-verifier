FROM ubuntu:24.04

ARG PY39_URL
ARG PY39_SHA256

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        g++-13 gcc-13 openjdk-21-jdk-headless \
        python3 ca-certificates curl xz-utils \
    && ln -sf /usr/bin/g++-13 /usr/bin/g++ \
    && ln -sf /usr/bin/gcc-13 /usr/bin/gcc \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$PY39_URL" -o /tmp/py39.tar.gz \
    && echo "$PY39_SHA256  /tmp/py39.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/python39 \
    && tar -xzf /tmp/py39.tar.gz -C /opt/python39 --strip-components=1 \
    && ln -sf /opt/python39/bin/python3.9 /usr/local/bin/python3.9 \
    && rm /tmp/py39.tar.gz

COPY runner.py /usr/local/bin/runner.py
COPY interactive_runner.py /usr/local/bin/interactive_runner.py
COPY languages/ /usr/local/lib/icpc/languages/
COPY bench/bench.c /tmp/bench.c

RUN chmod +x /usr/local/bin/runner.py /usr/local/bin/interactive_runner.py \
        /usr/local/lib/icpc/languages/*.sh \
    && ln -sf /usr/local/lib/icpc/languages/compile.sh /usr/local/lib/icpc/compile.sh \
    && ln -sf /usr/local/lib/icpc/languages/run.sh /usr/local/lib/icpc/run.sh \
    && gcc -O2 -o /usr/local/bin/bench /tmp/bench.c && rm /tmp/bench.c

# 기준 시간을 3회 중앙값으로 잰다
RUN set -eu; \
    a=$(/usr/local/bin/bench 2>/dev/null); \
    b=$(/usr/local/bin/bench 2>/dev/null); \
    c=$(/usr/local/bin/bench 2>/dev/null); \
    printf '%s\n%s\n%s\n' "$a" "$b" "$c" | sort -g | sed -n 2p \
      > /usr/local/lib/icpc/BENCH_REFERENCE; \
    cat /usr/local/lib/icpc/BENCH_REFERENCE

WORKDIR /work
