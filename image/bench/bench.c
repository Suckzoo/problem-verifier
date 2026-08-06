/* machine factor 측정용 고정 benchmark.
   정수, 부동소수, 메모리 접근을 섞는다. 결과 초를 stdout 에 출력한다. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define N (1 << 22)

int main(void) {
    uint32_t *a = malloc(N * sizeof(uint32_t));
    double acc = 0.0;
    uint64_t h = 1469598103934665603ULL;

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int i = 0; i < N; i++) a[i] = (uint32_t)(i * 2654435761u);
    for (int round = 0; round < 8; round++) {
        for (int i = 0; i < N; i++) {
            h ^= a[(i * 7919u) & (N - 1)];
            h *= 1099511628211ULL;
            acc += (double)(h >> 40) * 1e-9;
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double seconds = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) * 1e-9;
    fprintf(stderr, "%f %llu\n", acc, (unsigned long long)h);
    printf("%.6f\n", seconds);
    free(a);
    return 0;
}
