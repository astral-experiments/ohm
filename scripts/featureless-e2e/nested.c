/* A native nested compiler/driver/linker chain and a disjoint execution. */
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void run(const char *dir, const char *role, const char *amount) {
    char p[PATH_MAX];
    int n = snprintf(p, sizeof(p), "%s/%s", dir, role);
    if (n < 0 || n >= (int)sizeof(p)) exit(120);
    pid_t pid = fork();
    if (pid < 0) exit(121);
    if (pid == 0) { execl(p, p, "selected", dir, amount, (char *)0); _exit(122); }
    int st;
    if (waitpid(pid, &st, 0) != pid || !WIFEXITED(st) || WEXITSTATUS(st) != 0) exit(123);
}
static void *loop(void *arg) {
    unsigned long n = *(unsigned long *)arg;
    if (n) __asm__ volatile ("1: sub $1, %0\n\tjne 1b" : "+r"(n) : : "cc");
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 4) return 119;
    const char *role = strrchr(argv[0], '/');
    if (role == NULL) return 118;
    role++;
    unsigned long loops = strtoul(argv[3], NULL, 10);
    if (!strcmp(role, "nested")) {
        run(argv[2], "build_rustc", argv[3]); run(argv[2], "generator", argv[3]);
    } else if (!strcmp(role, "build_rustc")) run(argv[2], "unicode_rustc", argv[3]);
    else if (!strcmp(role, "generator")) loops *= 3;
    else if (!strcmp(role, "unicode_rustc")) { loops *= 5; run(argv[2], "ron", argv[3]); }
    else if (!strcmp(role, "ron")) loops *= 7;
    else return 117;
    if (!strcmp(role, "ron")) {
        pthread_t t;
        if (pthread_create(&t, NULL, loop, &loops) || pthread_join(t, NULL)) return 116;
    } else loop(&loops);
    return 0;
}
