#include <stdint.h>
#include <stdio.h>

extern uint32_t probe(uint32_t *);

int main(void) {
    uint32_t slot = 0;
    const uint32_t result = probe(&slot);
    printf("%u %u\n", result, slot);
    return result != 19 || slot != 19;
}
