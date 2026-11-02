#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static long long monotonic_ns(void) {
    struct timespec stamp;
    if (clock_gettime(CLOCK_MONOTONIC, &stamp) != 0) _exit(71);
    return stamp.tv_sec * 1000000000LL + stamp.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 3) return 64;
    char *end = NULL;
    long delay_ms = strtol(argv[1], &end, 10);
    if (*end || delay_ms < 0 || delay_ms > 1000) return 65;
    long exit_code = strtol(argv[2], &end, 10);
    if (*end || exit_code < 0 || exit_code > 127) return 66;
    long long first = monotonic_ns();
    long long until = first + 1000000LL * delay_ms;
    struct timespec deadline = {(time_t) (until / 1000000000LL), (long) (until % 1000000000LL)};
    int err;
    do {
        err = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
    } while (err == EINTR);
    if (err) return 67;
    long long last = monotonic_ns();
    if (dprintf(STDOUT_FILENO, "%ld %lld %lld\n", (long) getpid(), first, last) < 0) return 68;
    _exit((int) exit_code);
}
