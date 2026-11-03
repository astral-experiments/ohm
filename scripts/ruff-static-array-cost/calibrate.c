#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void work(void) {
    volatile uint64_t accumulator = 17;
    for (uint64_t i = 0; i < 20000000; ++i)
        accumulator = accumulator * 33 + i;
}

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    work();
    if (!strcmp(argv[1], "single"))
        return 0;
    if (strcmp(argv[1], "fork"))
        return 3;
    pid_t child = fork();
    if (child < 0)
        return 4;
    if (child == 0) {
        work();
        _exit(0);
    }
    int status;
    return waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 5;
}
