#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

void *reserve_physical(void) { return malloc(64); }
extern uint64_t observed(void);
int main(void) {
    printf("%" PRIu64 "\n", observed());
    return 0;
}
