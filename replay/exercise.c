#include <err.h>
#include <pthread.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

static void *work(void *arg) {
    unsigned long n = strtoul(arg, NULL, 10);
    if (n)
        __asm__ volatile("1: dec %0; jnz 1b" : "+r"(n) : : "cc");
    return NULL;
}

static void spawn(char *exe, char *n) {
    int status;
    pid_t pid = fork();
    if (pid < 0) err(1, "fork");
    if (!pid) {
        execl(exe, exe, n, NULL);
        _exit(1);
    }
    if (waitpid(pid, &status, 0) != pid || status)
        errx(1, "worker failed");
}

int main(int argc, char **argv) {
    if (argc != 2 && argc != 3) return 1;
    work(argv[1]);
    if (argc == 3) {
        pthread_t worker;
        if (pthread_create(&worker, NULL, work, argv[1]) || pthread_join(worker, NULL))
            errx(1, "worker thread failed");
        spawn(argv[0], argv[1]);
        spawn(argv[2], argv[1]);
    }
    return 0;
}
