#include <chrono>
#include <cstdio>
#include <thread>
int main() {
    std::this_thread::sleep_for(std::chrono::seconds(10));
    puts("0");
    return 0;
}
