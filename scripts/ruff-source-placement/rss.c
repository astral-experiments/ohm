#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

/* Stay outside strace and the inherited hardware event. Open the evidence path after the child exits. */
int main(int argc, char **argv) {
    if (argc < 3 || argv[2][0] != '/') return 125;
    pid_t child = fork();
    if (child < 0) return 125;
    if (child == 0) {
        execv(argv[2], argv + 2);
        _exit(127);
    }
    struct rusage usage = {0};
    int status;
    pid_t reaped;
    do { reaped = wait4(child, &status, 0, &usage); } while (reaped < 0 && errno == EINTR);
    if (reaped != child || usage.ru_maxrss <= 0) return 125;
    int fd = open(argv[1], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return 125;
    int result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    if (dprintf(fd, "{\"child_pid\":%d,\"status\":%d,\"maxrss_kib\":%ld,\"user_us\":%lld,\"system_us\":%lld}\n",
           child, status, usage.ru_maxrss,
           (long long)usage.ru_utime.tv_sec*1000000+usage.ru_utime.tv_usec,
           (long long)usage.ru_stime.tv_sec*1000000+usage.ru_stime.tv_usec) < 0 ||
        fsync(fd) < 0 || close(fd) < 0) return 125;
    return result;
}
