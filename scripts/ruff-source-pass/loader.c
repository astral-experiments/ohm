#define _XOPEN_SOURCE 700
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void fail(const char *s) {
    dprintf(2, "Ohm source pass loader: %s\n", s);
    _exit(125);
}

/* This DSO is preloaded only into the signed rustc selected by the launcher. */
__attribute__((constructor)) static void enter(void) {
    const char *base = getenv("OHM_SOURCE_PASS_DIR");
    const char *compiler = getenv("OHM_SOURCE_PASS_RUSTC");
    const char *preload = getenv("LD_PRELOAD");
    struct stat expected, actual;
    char path[PATH_MAX];
    if (!base || base[0] != '/' || !compiler || !preload ||
        stat(compiler, &expected) || stat("/proc/self/exe", &actual) ||
        expected.st_dev != actual.st_dev || expected.st_ino != actual.st_ino)
        fail("not the intended signed compiler process");
    int n = snprintf(path, sizeof(path), "%s/loader.so", base);
    if (n < 0 || (size_t)n >= sizeof(path) || strcmp(path, preload) || unsetenv("LD_PRELOAD"))
        fail("cannot remove the private preload before descendants");
    n = snprintf(path, sizeof(path), "%s/active.so", base);
    if (n < 0 || (size_t)n >= sizeof(path)) fail("plugin path too long");
    /* Its machine-pass callback stays registered for the life of this rustc. */
    if (!dlopen(path, RTLD_NOW | RTLD_LOCAL)) fail(dlerror());
    const char *audit = getenv("OHM_SOURCE_PASS_AUDIT");
    if (audit) {
        if (audit[0] != '/' || stat(path, &actual)) fail("invalid native receipt");
        n = snprintf(path, sizeof(path), "%s/%ld.load", audit, (long)getpid());
        if (n < 0 || (size_t)n >= sizeof(path)) fail("native receipt path too long");
        int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd < 0 || dprintf(fd, "%ju %ju\n", (uintmax_t)actual.st_dev,
                             (uintmax_t)actual.st_ino) < 0 || close(fd)) fail("cannot write native receipt");
    }
}
