#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 4) return 2;
    int gate[2];
    if (pipe(gate)) return 3;
    pid_t child = fork();
    if (child < 0) return 4;
    if (!child) {
        close(gate[1]);
        char token;
        if (read(gate[0], &token, 1) != 1) _exit(125);
        close(gate[0]);
        execvp(argv[3], &argv[3]);
        _exit(127);
    }
    close(gate[0]);
    struct perf_event_attr attr = {0};
    attr.size = sizeof(attr);
    attr.type = PERF_TYPE_HARDWARE;
    attr.config = PERF_COUNT_HW_INSTRUCTIONS;
    attr.disabled = 1;
    attr.enable_on_exec = 1;
    attr.inherit = 1;
    attr.pinned = 1;
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;
    attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    int fd = syscall(SYS_perf_event_open, &attr, child, -1, -1, 0);
    if (fd < 0) {
        perror("perf_event_open");
        kill(child, SIGKILL);
        waitpid(child, 0, 0);
        return 5;
    }
    uint64_t event_id = 0;
    if (ioctl(fd, PERF_EVENT_IOC_ID, &event_id)) return 6;
    if (write(gate[1], "x", 1) != 1) return 7;
    close(gate[1]);
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 8;
    struct { uint64_t value, enabled, running; } result;
    ssize_t bytes = read(fd, &result, sizeof(result));
    close(fd);
    if (bytes != (ssize_t)sizeof(result)) return 9;
    FILE *out = fopen(argv[1], "wx");
    if (!out) return 10;
    fprintf(out, "{\"instructions\":%"PRIu64",\"time_enabled\":%"PRIu64",\"time_running\":%"PRIu64",\"event_id\":%"PRIu64",\"child_pid\":%d,\"raw_wait_status\":%d,\"inherit\":true,\"exclude_kernel\":true,\"exclude_hv\":true,\"enable_on_exec\":true}\n", result.value, result.enabled, result.running, event_id, child, status);
    fclose(out);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
