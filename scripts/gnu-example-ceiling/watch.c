#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void failed(const char *why) { perror(why); exit(120); }
static int64_t now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) failed("monotonic clock");
    return (int64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}
static int64_t microseconds(struct timeval v) { return (int64_t)v.tv_sec * 1000000 + v.tv_usec; }

int main(int argc, char **argv) {
    if (argc < 3) return 121;
    int syncfd[2];
    if (pipe2(syncfd, O_CLOEXEC)) failed("pipe");
    pid_t pid = fork();
    if (pid < 0) failed("fork");
    if (pid == 0) {
        close(syncfd[1]);
        char go;
        if (read(syncfd[0], &go, 1) != 1) _exit(122);
        close(syncfd[0]);
        execvp(argv[2], argv + 2);
        _exit(127);
    }
    close(syncfd[0]);
    struct perf_event_attr event = {
        .type = PERF_TYPE_HARDWARE, .size = sizeof(event), .config = PERF_COUNT_HW_INSTRUCTIONS,
        .inherit = 1, .disabled = 1, .enable_on_exec = 1, .exclude_kernel = 1, .exclude_hv = 1,
        .read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    int fd = syscall(SYS_perf_event_open, &event, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    int event_errno = fd < 0 ? errno : 0;
    int64_t start = now();
    if (write(syncfd[1], "x", 1) != 1) failed("release");
    close(syncfd[1]);
    int status;
    struct rusage usage = {0};
    while (wait4(pid, &status, 0, &usage) != pid)
        if (errno != EINTR) failed("wait");
    int64_t stop = now();
    uint64_t values[3] = {0};
    if (fd >= 0) {
        if (read(fd, values, sizeof(values)) != sizeof(values)) failed("read counter");
        close(fd);
    }
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    FILE *out = fopen(argv[1], "wx");
    if (!out) failed("new results file");
    fprintf(out, "{\"start\":%" PRId64 ",\"stop\":%" PRId64 ",\"user_us\":%" PRId64
        ",\"system_us\":%" PRId64 ",\"instructions\":%" PRIu64 ",\"enabled\":%" PRIu64
        ",\"running\":%" PRIu64 ",\"event_errno\":%d,\"code\":%d}\n",
        start, stop, microseconds(usage.ru_utime), microseconds(usage.ru_stime),
        values[0], values[1], values[2], event_errno, code);
    if (fclose(out)) failed("close results");
    return code;
}
