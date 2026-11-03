#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static void *worker(void *input) {
    uint64_t n = (uint64_t)(uintptr_t)input, value=0;
    __asm__ volatile("1: inc %[v]\n\tadd $3, %[v]\n\tsub $1, %[n]\n\tjne 1b"
                     : [n] "+r"(n), [v] "+r"(value) : : "cc");
    return (void *)(uintptr_t)value;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    uint64_t n = strtoull(argv[1], NULL, 10);
    pthread_t threads[2];
    for (unsigned i=0;i<2;i++) if (pthread_create(&threads[i],NULL,worker,(void *)(uintptr_t)n)) return 2;
    uint64_t sum=0;
    for (unsigned i=0;i<2;i++) {
        void *v=NULL;
        if (pthread_join(threads[i],&v)) return 2;
        sum += (uint64_t)(uintptr_t)v;
    }
    printf("two actual workers %llu\n",(unsigned long long)sum);
    return sum!=8*n;
}
