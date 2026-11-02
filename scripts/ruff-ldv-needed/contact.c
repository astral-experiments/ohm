/* Contact for glibc's constructor ABI. No loader state is inherited by exec. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static void all(int fd, const char *data, size_t left) {
    while (left) {
        ssize_t n = write(fd, data, left);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) _exit(116);
        data += n;
        left -= (size_t)n;
    }
}

static int record(const char *directory, const char *suffix) {
    char path[PATH_MAX];
    int n = snprintf(path, sizeof(path), "%s/%ld.%s", directory, (long)getpid(), suffix);
    if (n <= 0 || (size_t)n >= sizeof(path)) _exit(117);
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) _exit(117);
    return fd;
}

/* Preserve the real compiler's stderr for Cargo and the separate PID witness.
   The child has no jobserver descriptors and never executes another program. */
static void tee_stderr(const char *directory) {
    int out = record(directory, "stderr");
    int ends[2];
    if (pipe2(ends, O_CLOEXEC)) _exit(118);
    pid_t child = fork();
    if (child < 0) _exit(118);
    if (!child) {
        if (dup2(ends[0], 0) < 0 || dup2(out, 1) < 0 ||
            syscall(SYS_close_range, 3U, ~0U, 0U)) _exit(118);
        char buffer[16384];
        for (;;) {
            ssize_t n = read(0, buffer, sizeof(buffer));
            if (n < 0 && errno == EINTR) continue;
            if (n < 0) _exit(118);
            if (n == 0) _exit(0);
            all(1, buffer, (size_t)n);
            all(2, buffer, (size_t)n);
        }
    }
    if (dup2(ends[1], 2) < 0) _exit(118);
    close(out);
    close(ends[0]);
    close(ends[1]);
}

static int same(const char *a, const char *b, struct stat *actual) {
    struct stat expected;
    return a && b && !stat(a, actual) && !stat(b, &expected) &&
           actual->st_dev == expected.st_dev && actual->st_ino == expected.st_ino;
}

__attribute__((constructor))
static void contact(int argc, char **argv, char **envp) {
    (void)envp;
    const char *directory = getenv("QA_LDV_RECORD");
    if (!directory) return;
    struct stat front, llvm;
    if (!same("/proc/self/exe", getenv("QA_LDV_FRONTEND"), &front)) return;
    int selected = 0;
    for (int i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--crate-name")) selected = 1;
    if (!selected) return;
    if (getenv("LD_PRELOAD") || getenv("LD_AUDIT") || getenv("RUSTC_WRAPPER")) _exit(120);
    const char *mode = getenv("OHM_LDV_GUARD");
    const char *plugin = getenv("QA_LDV_PLUGIN");
    if (!mode || !plugin || (strcmp(mode, "guard") && strcmp(mode, "original"))) _exit(121);
    tee_stderr(directory);
    void *handle = dlopen(plugin, RTLD_NOW | RTLD_LOCAL);
    if (!handle) { dprintf(2, "LDV dlopen: %s\n", dlerror()); _exit(122); }
    Dl_info info;
    if (!dlsym(handle, "llvmGetPassPluginInfo") ||
        !dladdr(dlsym(handle, "LLVMRunPasses"), &info) ||
        !same(info.dli_fname, getenv("QA_LDV_LLVM"), &llvm)) _exit(123);
    int fd = record(directory, "loaded");
    char text[180];
    int n = snprintf(text, sizeof(text), "%s %llu %llu %llu %llu\n", mode,
                     (unsigned long long)front.st_dev, (unsigned long long)front.st_ino,
                     (unsigned long long)llvm.st_dev, (unsigned long long)llvm.st_ino);
    if (n <= 0 || (size_t)n >= sizeof(text)) _exit(124);
    all(fd, text, (size_t)n);
    if (close(fd)) _exit(124);
}
