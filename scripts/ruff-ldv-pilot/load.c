#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <link.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int same_file(const char *left, const char *right) {
    struct stat a, b;
    return stat(left, &a) == 0 && stat(right, &b) == 0 && a.st_dev == b.st_dev && a.st_ino == b.st_ino;
}
__attribute__((constructor))
static void install_guard(void) {
    const char *front = getenv("QA_LDV_FRONTEND");
    const char *plugin = getenv("QA_LDV_PLUGIN");
    const char *library = getenv("QA_LDV_LLVM");
    if (!front || !plugin || !library || !same_file("/proc/self/exe", front)) _exit(120);
    if (unsetenv("LD_PRELOAD") != 0 || getenv("LD_PRELOAD")) _exit(121);
    void *handle = dlopen(plugin, RTLD_NOW | RTLD_LOCAL);
    if (!handle) { fprintf(stderr, "LDV probe dlopen: %s\n", dlerror()); _exit(122); }
    Dl_info info;
    if (!dlsym(handle, "llvmGetPassPluginInfo") ||
        !dladdr(dlsym(handle, "LLVMRunPasses"), &info) ||
        !same_file(info.dli_fname, library)) _exit(123);
}
