/* Native syscall admission test. Called only outside the measured command. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    errno = 0;
    int fd = open64(argv[1], atoi(argv[2]), 0600);
    int error = fd < 0 ? errno : 0;
    printf("%d %d\n", fd >= 0, error);
    if (fd >= 0 && close(fd) != 0) return 3;
    return 0;
}
