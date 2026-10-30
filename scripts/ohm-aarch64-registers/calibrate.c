#include <errno.h>
#include <pthread.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>

extern char **environ;
static void *work(void *arg) {
    volatile uint64_t value = 17;
    uintptr_t count = (uintptr_t)arg;
    for (uintptr_t i = 0; i < count; i++)
        value = value * 31 + i;
    return (void *)(uintptr_t)(value & 0xff);
}

int main(int argc, char **argv) {
    if (argc < 3)
        return 70;
    uintptr_t count = strtoul(argv[2], 0, 10);
    if (!strcmp(argv[1], "child")) {
        work((void *)count);
        return 0;
    }
    if (argc != 5 || strcmp(argv[1], "parent"))
        return 71;
    pthread_t thread;
    if (pthread_create(&thread, NULL, work, (void *)count))
        return 72;
    if (strcmp(argv[3], "0")) {
        char *child[] = {argv[4], "child", argv[3], NULL};
        pid_t pid;
        if (posix_spawn(&pid, child[0], NULL, NULL, child, environ))
            return 73;
        int status;
        while (waitpid(pid, &status, 0) < 0)
            if (errno != EINTR)
                return 74;
        if (!WIFEXITED(status) || WEXITSTATUS(status))
            return 75;
    }
    return pthread_join(thread, NULL) ? 76 : 0;
}
