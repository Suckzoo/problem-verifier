#include <cstdio>
#include <cstring>
int main() {
    long long lo = 1, hi = 100;
    char resp[32];
    while (lo <= hi) {
        long long mid = (lo + hi) / 2;
        printf("%lld\n", mid);
        fflush(stdout);
        if (scanf("%31s", resp) != 1) return 1;
        if (strcmp(resp, "correct") == 0) return 0;
        if (strcmp(resp, "higher") == 0) lo = mid + 1;
        else hi = mid - 1;
    }
    return 0;
}
