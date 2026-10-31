#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Only the calling test program's own children/threads. Every attempted image is
 * invalid at the kernel, even if the tracer loses its userspace memory on exit. */
static atomic_uint attempts;
static void *invalid_exec(void *unused) {
    (void)unused;
    for (;;) {
        if (syscall(SYS_execve, (uintptr_t)0x12345000, (uintptr_t)0x12346000,
                    (uintptr_t)0x12347000) != -1 || errno != EFAULT) _exit(92);
        atomic_fetch_add_explicit(&attempts, 1, memory_order_relaxed);
    }
    return NULL;
}

int main(int argc, char **argv) {
    unsigned groups = argc == 2 ? (unsigned)atoi(argv[1]) : 0;
    if (groups == 0 || groups > 60) return 93;
    for (unsigned i = 0; i < groups; ++i) {
        pid_t child = fork();
        if (child < 0) return 94;
        if (!child) {
            for (unsigned t = 0; t < 5; ++t) {
                pthread_t thread;
                if (pthread_create(&thread, NULL, invalid_exec, NULL)) _exit(95);
            }
            while (!atomic_load_explicit(&attempts, memory_order_relaxed)) sched_yield();
            _exit(42);
        }
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status) != 42) return 96;
    }
    printf("valid parent exits across %u groups\n", groups);
    return 0;
}
