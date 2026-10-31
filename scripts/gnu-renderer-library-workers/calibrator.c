#define _GNU_SOURCE
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct work { const char *name; uint64_t iterations; };
static void loop(uint64_t n) {
    if (n) __asm__ volatile("1: sub $1, %0\n\tjne 1b" : "+r"(n) :: "cc");
}
static void *run(void *opaque) {
    struct work *w=opaque;
    if (pthread_setname_np(pthread_self(), w->name)) abort();
    loop(w->iterations);
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 7 || strcmp(argv[1],"--crate-name") || strcmp(argv[3],"--out-dir")) return 3;
    uint64_t n = strtoul(argv[5],NULL,10);
    if (n > 200000000 || strcmp(argv[6], "fixture")) return 4;
    struct work w[]={{"opt abcdefghijk",n}, {"opt 123456789ab",2*n}, {"cpy zyxwvutsrqp",3*n}, {"outside",5*n}};
    pthread_t threads[4];
    for (unsigned i=0;i<4;i++) if (pthread_create(&threads[i],NULL,run,&w[i])) abort();
    for (unsigned i=0;i<4;i++) if (pthread_join(threads[i],NULL)) abort();
    return 0;
}
