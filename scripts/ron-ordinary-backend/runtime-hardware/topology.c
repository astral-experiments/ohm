#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

static int observe(const char *name, const void *pc, int fd) {
    struct stat held, named;
    FILE *maps = fopen("/proc/self/maps", "r");
    char *line = NULL;
    size_t cap = 0;
    int found = -1;
    if (!maps || fstat(fd, &held) || stat(name, &named)) return -1;
    while (getline(&line, &cap, maps) > 0) {
        unsigned long low, high, offset, ino;
        unsigned ma, mi;
        char perms[5];
        if (sscanf(line, "%lx-%lx %4s %lx %x:%x %lu", &low, &high, perms, &offset, &ma, &mi, &ino) != 7) continue;
        const uintptr_t addr = (uintptr_t)pc;
        if (low > addr || addr >= high) continue;
        if (found != -1 || perms[2] != 'x') { found = -1; break; }
        found = held.st_dev == named.st_dev && held.st_ino == named.st_ino &&
                major(held.st_dev) == ma && minor(held.st_dev) == mi && held.st_ino == ino;
        printf("%s\t%u:%u\t%ju\t%u:%u\t%lu\t%s\t%lx\t%d\n", name,
               major(held.st_dev), minor(held.st_dev), (uintmax_t)held.st_ino, ma, mi, ino, perms, offset, found);
    }
    free(line);
    fclose(maps);
    return found;
}

int main(int argc, char **argv) {
    if (argc != 9) return 2;
    void *handle = dlopen(argv[3], RTLD_NOW | RTLD_LOCAL);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 3; }
    int (*value)(void) = (int (*)(void))dlsym(handle, "sample_value");
    void *libc = dlsym(RTLD_DEFAULT, "getenv");
    if (!value || value() != 17 || !libc) return 4;
    const void *pcs[] = {(const void *)main, (const void *)value, libc};
    int all = 1;
    for (int i = 0; i < 3; i++) {
        int found = observe(argv[2 + i], pcs[i], atoi(argv[5 + i]));
        if (found < 0) return 5;
        all &= found;
    }
    if (strcmp(argv[8], "three-private-physical-images")) return 6;
    return strcmp(argv[1], "observe") != 0 && !all ? 7 : 0;
}
