#define _GNU_SOURCE 1
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifndef REPLACE_CODE
#error encode an explicit four-character code
#endif
typedef int (*main_t)(int, char **, char **);
typedef int (*start_t)(main_t, int, char **, void (*)(void), void (*)(void), void (*)(void), void *);
static main_t real_main;

static int observe_main(int argc, char **argv, char **envp) {
    int result = real_main(argc, argv, envp);
    const char *out = getenv("OUT_DIR");
    const char *pkg = getenv("CARGO_PKG_NAME");
    if (result || !out || !pkg || strcmp(pkg, "ruff_unicode_names2")) return result;
    if (!strstr(out, "/host-unicode-wild-dir-v1/work.")) return 91;
    char path[4096], buffer[65536];
    if (snprintf(path, sizeof(path), "%s/generated_alias.rs", out) >= (int)sizeof(path)) return 92;
    FILE *file = fopen(path, "r+b");
    if (!file) return 93;
    size_t len = fread(buffer, 1, sizeof(buffer)-1, file);
    if (!len || len == sizeof(buffer)-1) return 94;
    buffer[len] = 0;
    const char *prefix = "(b\"NULL\", '\\u{";
    char *p = strstr(buffer, prefix);
    if (!p || strstr(p+1, prefix)) return 95;
    p += strlen(prefix);
    if (strncmp(p, "0000}", 5) || fseek(file, p-buffer, SEEK_SET) || fwrite(REPLACE_CODE,1,4,file)!=4 || fclose(file)) return 96;
    return 0;
}
int __libc_start_main(main_t main, int argc, char **argv, void (*init)(void), void (*fini)(void), void (*rtld)(void), void *stack) {
    start_t prior = (start_t)dlsym(RTLD_NEXT, "__libc_start_main");
    if (!prior) _exit(90);
    real_main=main;
    return prior(observe_main, argc, argv, init, fini, rtld, stack);
}
