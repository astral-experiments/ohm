#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/syscall.h>
/* A side copy of this compiler's exact stderr distinguishes native pass output
 * from Cargo replaying stored diagnostics for a fresh crate. The relay inherits
 * neither the loader nor Cargo's jobserver. The PMU includes the relay. */
static void send_all(int fd, const char *bytes, size_t length) {
    while (length) {
        ssize_t n = write(fd, bytes, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) _exit(119);
        bytes += n;
        length -= n;
    }
}
static void copy_stderr(void) {
    const char *dir = getenv("QA_LDV_RECORD");
    if (!dir) return;
    char path[PATH_MAX];
    int size = snprintf(path, sizeof(path), "%s/%ld.stderr", dir, (long)getpid());
    if (size < 0 || (size_t)size >= sizeof(path)) _exit(118);
    int out = open(path, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
    int keep[2];
    if (out < 0 || pipe2(keep, O_CLOEXEC)) _exit(118);
    pid_t pid = fork();
    if (pid < 0) _exit(118);
    if (!pid) {
        if (dup2(keep[0], 0) < 0 || dup2(out, 1) < 0 ||
            syscall(SYS_close_range, 3U, ~0U, 0U) != 0) _exit(118);
        char body[16384];
        for (;;) {
            ssize_t n = read(0, body, sizeof(body));
            if (!n) _exit(0);
            if (n < 0 && errno == EINTR) continue;
            if (n < 0) _exit(118);
            send_all(1, body, n);
            send_all(2, body, n);
        }
    }
    if (dup2(keep[1], 2) < 0) _exit(118);
    close(keep[0]); close(keep[1]); close(out);
}
int main(int argc, char **argv) {
    if (argc < 2) return 124;
    int compile = 0;
    for (int i = 2; i + 1 < argc; i++) if (!strcmp(argv[i], "--crate-name")) compile = 1;
    if (compile) copy_stderr();
    const char *enable = getenv("QA_LDV_INJECT");
    if (compile && enable && !strcmp(enable, "implicit")) {
        const char *shim = getenv("QA_LDV_SHIM");
        if (getenv("LD_PRELOAD") || !shim || setenv("LD_PRELOAD", shim, 1)) return 125;
    }
    execvp(argv[1], argv + 1);
    perror("execvp rustc");
    return 126;
}
