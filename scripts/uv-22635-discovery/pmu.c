#define _GNU_SOURCE
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <errno.h>

/* The tracer calls this while the successful exec is stopped. At that point
 * the new image has one thread and has not executed any user instructions. */
int ohm_open_user_instructions(int pid) {
    const struct perf_event_attr attr = {
        .size = sizeof(struct perf_event_attr),
        .type = PERF_TYPE_HARDWARE,
        .config = PERF_COUNT_HW_INSTRUCTIONS,
        .disabled = 1,
        .pinned = 1,
        .inherit = 1,
        .inherit_thread = 1,
        .exclude_kernel = 1,
        .exclude_hv = 1,
        .read_format = PERF_FORMAT_TOTAL_TIME_ENABLED |
                       PERF_FORMAT_TOTAL_TIME_RUNNING | PERF_FORMAT_ID,
    };
    int fd = syscall(__NR_perf_event_open, &attr, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    if (fd < 0)
        return -1;
    if (ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) < 0) {
        int error = errno;
        close(fd);
        errno = error;
        return -1;
    }
    return fd;
}
