#define _GNU_SOURCE
#include <linux/perf_event.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Count only this live thread. Children, the observer, and a later exec are excluded. */
int open_task_counter(int tid) {
    struct perf_event_attr attr = {
        .type = PERF_TYPE_HARDWARE,
        .size = sizeof(attr),
        .config = PERF_COUNT_HW_INSTRUCTIONS,
        .exclude_kernel = 1,
        .exclude_hv = 1,
        .remove_on_exec = 1,
        .read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    return syscall(__NR_perf_event_open, &attr, tid, -1, -1, PERF_FLAG_FD_CLOEXEC);
}
