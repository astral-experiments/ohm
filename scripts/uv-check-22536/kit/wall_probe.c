#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static int64_t now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) exit(99);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 3) return 98;
    long ms = strtol(argv[1], NULL, 10);
    if (ms < 0 || ms > 3000) return 97;
    int64_t start = now(), limit = start + ms * 1000000LL;
    struct timespec until = {limit / 1000000000LL, limit % 1000000000LL};
    int rc;
    do rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &until, NULL);
    while (rc == EINTR);
    if (rc != 0) return 96;
    printf("%" PRId64 " %" PRId64 "\n", start, now());
    return (int)strtol(argv[2], NULL, 10);
}
