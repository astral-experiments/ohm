#include <stdint.h>
#include <stdio.h>

extern uint64_t independent_llvm_mask(uint64_t, uint64_t);
extern uint64_t opaque_llvm_file(void);
extern uint32_t scan_words(const uint32_t *, const uint32_t *, uintptr_t, uint32_t);
extern void map_words(const double *, const double *, double *, uintptr_t);
extern void filled(uint8_t *, uintptr_t, uint8_t);

int main(void) {
    uint32_t xs[] = {2, 34, 55, 121};
    uint32_t ys[] = {7, 5, 9, 79};
    double a[] = {3, 7}, b[] = {2, 5}, dst[2] = {0};
    uint8_t buf[251] = {0};
    filled(buf, sizeof(buf), 31);
    map_words(a, b, dst, 2);
    printf("%llu %llu %u %.3f %u\n", (unsigned long long)opaque_llvm_file(),
           (unsigned long long)independent_llvm_mask(24, 1), scan_words(xs, ys, 4, 91),
           dst[1], (unsigned)buf[250]);
    return 0;
}
