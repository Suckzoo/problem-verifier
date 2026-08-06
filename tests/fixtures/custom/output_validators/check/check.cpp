#include <cstdio>
#include <cstdlib>
#include <string>
// sum checker: input 은 목표합 s, team 출력은 "a b". a+b==s 면 42, 아니면 43.
int main(int argc, char** argv) {
    FILE* in = fopen(argv[1], "r");
    long long s, a, b;
    if (fscanf(in, "%lld", &s) != 1) return 1;
    if (scanf("%lld %lld", &a, &b) != 2) {
        std::string path = std::string(argv[3]) + "/judgemessage.txt";
        FILE* fb = fopen(path.c_str(), "w");
        fprintf(fb, "two integers expected\n");
        fclose(fb);
        return 43;
    }
    if (a + b == s) return 42;
    std::string path = std::string(argv[3]) + "/judgemessage.txt";
    FILE* fb = fopen(path.c_str(), "w");
    fprintf(fb, "%lld + %lld != %lld\n", a, b, s);
    fclose(fb);
    return 43;
}
