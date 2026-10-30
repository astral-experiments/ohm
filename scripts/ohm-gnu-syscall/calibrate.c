#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    if (!strcmp(argv[1], "exec")) {
        execl("/usr/bin/env", "env", argv[0], "0", argv[2], argv[3], (char *)0);
        return 7;
    }
    int depth = atoi(argv[1]), copies = atoi(argv[3]);
    unsigned long count = strtoul(argv[2], NULL, 10);
    if (!depth) {
        if (count) __asm__ volatile("1: dec %0\n\tjne 1b" : "+r"(count) : : "cc");
        return 0;
    }
    for (int i = 0; i < copies; ++i) {
        pid_t pid = fork();
        if (pid < 0) return 3;
        if (!pid) {
            char text[8];
            if (snprintf(text, sizeof(text), "%d", depth - 1) < 1) _exit(6);
            execl(argv[0], argv[0], text, argv[2], "1", (char *)0);
            _exit(4);
        }
        int status;
        if (waitpid(pid, &status, 0) != pid || status != 0) return 5;
    }
    return 0;
}
