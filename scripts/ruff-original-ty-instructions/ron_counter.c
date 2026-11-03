#include <linux/perf_event.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Count only the signed inferior after main and its later children. GDB stays outside. */
int open_counter(int pid) {
    struct perf_event_attr attr = {
        .size = sizeof(attr), .type = PERF_TYPE_HARDWARE,
        .config = PERF_COUNT_HW_INSTRUCTIONS, .disabled = 1, .inherit = 1, .pinned = 1,
        .exclude_kernel = 1, .exclude_hv = 1,
        .read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    int fd = syscall(__NR_perf_event_open, &attr, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    if (fd < 0) return -1;
    if (ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) != 0) { close(fd); return -1; }
    return fd;
}

int finish_counter(int fd, uint64_t out[3]) {
    int ok = read(fd, out, 3*sizeof(*out)) == (ssize_t)(3*sizeof(*out));
    close(fd);
    return ok;
}
