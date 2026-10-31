#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void reject(const char *why) {
    fprintf(stderr, "workspace-wrapper enrollment rejected: %s\n", why);
    exit(124);
}

static void need(int test, const char *why) {
    if (!test) reject(why);
}

static int exact(int n, char **v, const char *s) {
    int count = 0;
    for (int i = 2; i < n; i++) count += !strcmp(s, v[i]);
    return count;
}

static const char *after(int n, char **v, const char *s) {
    const char *value = NULL;
    for (int i = 2; i < n - 1; i++) {
        if (!strcmp(v[i], s)) {
            need(value == NULL, "duplicated option");
            value = v[i + 1];
        }
    }
    return value;
}

int main(int argc, char **argv) {
    need(argc >= 2, "missing real rustc");
    const char *crate = after(argc, argv, "--crate-name");
    const char *source = "crates/ruff_unicode_names2_generator/src/lib.rs";
    const char *mode = getenv("OHM_BRIDGE_ARM");
    need(mode && strlen(mode) == 1 && strchr("ABQC", mode[0]), "unknown arm");
    const int selected = crate && !strcmp(crate, "unicode_names2_generator") && exact(argc, argv, source) == 1;
    if (selected) {
        struct stat compiler, expected;
        const char *rust = getenv("OHM_BRIDGE_RUSTC");
        const char *root = getenv("OHM_BRIDGE_RUFF");
        char cwd[PATH_MAX];
        need(rust && root && getcwd(cwd, sizeof(cwd)) && !strcmp(root, cwd), "wrong workspace root");
        need(!stat(rust, &expected) && !stat(argv[1], &compiler) && compiler.st_ino == expected.st_ino && compiler.st_dev == expected.st_dev, "wrong physical compiler");
        need(exact(argc, argv, "--emit=dep-info,metadata,link") == 1 && !exact(argc, argv, "--target"), "not host code generation");
        const char *kind = after(argc, argv, "--crate-type");
        need(kind && !strcmp(kind, "lib") && after(argc, argv, "--out-dir"), "not one emitted library");
        for (int i = 2; i < argc; i++) need(!strstr(argv[i], "share-generics"), "pre-existing share-generics option");
        const char *opt = !strcmp(mode, "A") ? NULL : !strcmp(mode, "C") ? "opt-level=2" : "opt-level=1";
        if (opt) need(exact(argc, argv, opt) == 1 && exact(argc, argv, "debug-assertions=on") == 1, "optimization or checked debug settings differ");
        if (!strcmp(mode, "Q")) {
            char **forward = calloc((size_t)argc + 1, sizeof(*forward));
            if (!forward) { perror("calloc"); return 125; }
            memcpy(forward, argv + 1, (size_t)(argc - 1) * sizeof(*forward));
            forward[argc - 1] = "-Zshare-generics=no";
            execvp(forward[0], forward);
            perror("exec selected rustc"); return 125;
        }
    }
    execvp(argv[1], argv + 1);
    perror("exec rustc"); return 125;
}
