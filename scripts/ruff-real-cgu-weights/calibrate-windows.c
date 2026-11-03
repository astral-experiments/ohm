#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct job {
    const char *name;
    uint64_t iterations;
    uint64_t value;
};

static void *write_object(void *input) {
    struct job *job = input;
    int fd = open(job->name, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) abort();
    uint64_t value = 1;
    for (uint64_t i = 0; i < job->iterations; i++) {
        value = value * UINT64_C(6364136223846793005) + i;
        __asm__ volatile("" : "+r"(value));
    }
    job->value = value;
    if (write(fd, &value, sizeof(value)) != (ssize_t)sizeof(value) || close(fd)) abort();
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 4 || strcmp(argv[1], "--crate-name") || strcmp(argv[2], "window_calibration") || chdir(argv[3])) return 1;
    struct job jobs[] = {{"window_short.o", 250000, 0}, {"window_long.o", 1000000, 0}};
    pthread_t workers[2];
    for (int n = 0; n < 2; n++) if (pthread_create(&workers[n], NULL, write_object, &jobs[n])) return 2;
    for (int n = 0; n < 2; n++) if (pthread_join(workers[n], NULL)) return 3;
    if (open("nonexistent/refused.o", O_WRONLY|O_CREAT, 0600) >= 0 || errno != ENOENT) return 4;
    return jobs[0].value == jobs[1].value;
}
