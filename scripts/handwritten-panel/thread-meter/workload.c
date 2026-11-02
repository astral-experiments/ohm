#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static uint64_t iterations;

static void *work(void *unused) {
    (void)unused;
    uint64_t n = iterations;
    __asm__ volatile ("1: sub $1, %0\n\tjne 1b" : "+r"(n) : : "cc");
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 3)
        return 1;
    char *end;
    errno = 0;
    iterations = strtoull(argv[2], &end, 10);
    if (errno || *end || !iterations || iterations > 100000000)
        return 2;
    if (!strcmp(argv[1], "serial")) {
        work(NULL);
    } else if (!strcmp(argv[1], "threads")) {
        pthread_t workers[3];
        for (int i = 0; i < 3; i++)
            if (pthread_create(&workers[i], NULL, work, NULL))
                return 3;
        for (int i = 0; i < 3; i++)
            if (pthread_join(workers[i], NULL))
                return 4;
    } else if (!strcmp(argv[1], "fork")) {
        pid_t child = fork();
        if (child < 0)
            return 5;
        if (child == 0) {
            work(NULL);
            _exit(0);
        }
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status))
            return 6;
    } else if (!strcmp(argv[1], "reexec")) {
        execl(argv[0], argv[0], "serial", argv[2], (char *)NULL);
        return 7;
    } else {
        return 8;
    }
    printf("completed %s %" PRIu64 "\n", argv[1], iterations);
    return 0;
}
