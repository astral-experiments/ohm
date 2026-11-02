#define _XOPEN_SOURCE 700
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void die(const char *why) {
    fprintf(stderr, "Ohm source pass launcher: %s\n", why);
    _exit(125);
}

static const char *required(const char *name) {
    const char *value = getenv(name);
    if (!value || value[0] != '/') die(name);
    return value;
}

static void child_path(char dest[PATH_MAX], const char *dir, const char *file) {
    int count = snprintf(dest, PATH_MAX, "%s/%s", dir, file);
    if (count < 0 || count >= PATH_MAX) die("path too long");
}

static bool same_file(const char *a, const char *b) {
    struct stat x, y;
    return stat(a, &x) == 0 && stat(b, &y) == 0 &&
           S_ISREG(x.st_mode) && x.st_dev == y.st_dev && x.st_ino == y.st_ino;
}

static bool native_output(const char *outputs) {
    while (*outputs) {
        const char *end = strchr(outputs, ',');
        const char *eq = strchr(outputs, '=');
        size_t count = end ? (size_t)(end - outputs) : strlen(outputs);
        size_t n = (eq && (size_t)(eq - outputs) < count) ? (size_t)(eq - outputs) : count;
        if ((n == 4 && !memcmp(outputs, "link", n)) || (n == 3 && !memcmp(outputs, "obj", n)) ||
            (n == 3 && !memcmp(outputs, "asm", n)) || (n == 7 && !memcmp(outputs, "llvm-bc", n)) ||
            (n == 7 && !memcmp(outputs, "llvm-ir", n))) return true;
        if (!end) break;
        outputs = end + 1;
    }
    return false;
}

static bool owner_codegen(int argc, char **argv, const char *workspace) {
    const char *name = NULL;
    bool native = false, custom = false, test = false;
    for (int i = 2; i < argc; ++i) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--crate-name") && i + 1 < argc) name = argv[++i];
        else if (!strcmp(arg, "--emit") && i + 1 < argc) native |= native_output(argv[++i]);
        else if (!strncmp(arg, "--emit=", 7)) native |= native_output(arg + 7);
        else if (!strcmp(arg, "--test")) test = true;
        else if (!strcmp(arg, "-Zno-codegen") || !strcmp(arg, "-vV") || !strcmp(arg, "--version") ||
                 !strcmp(arg, "--print") || !strncmp(arg, "--print=", 8)) return false;
        else if (!strncmp(arg, "-Cllvm-args", 11) || !strncmp(arg, "-Zllvm-plugins", 14) ||
                 (!strcmp(arg, "-C") && i + 1 < argc && !strncmp(argv[i + 1], "llvm-args", 9)) ||
                 (!strcmp(arg, "-Z") && i + 1 < argc && !strncmp(argv[i + 1], "llvm-plugins", 12))) custom = true;
    }
    if (!name || !native) return false;
    const char *source;
    if (!test && !strcmp(name, "ruff_workspace")) source = "crates/ruff_workspace/src/lib.rs";
    else if (!test && !strcmp(name, "ty_server")) source = "crates/ty_server/src/lib.rs";
    else if (test && !strcmp(name, "e2e")) source = "crates/ty_server/tests/e2e/main.rs";
    else return false;
    char original[PATH_MAX], actual[PATH_MAX];
    child_path(original, workspace, source);
    for (int i = 2; i < argc; ++i) {
        size_t length = strlen(argv[i]);
        if (length > 3 && !strcmp(argv[i] + length - 3, ".rs") &&
            realpath(argv[i], actual) && !strcmp(original, actual)) {
            if (custom) die("unexpected manual LLVM input on an enrolled owner");
            return true;
        }
    }
    return false;
}

static void audit(int argc, char **argv, const char *event) {
    const char *dir = getenv("OHM_SOURCE_PASS_AUDIT");
    if (!dir) return;
    char name[64], path[PATH_MAX];
    if (dir[0] != '/' || snprintf(name, sizeof(name), "%ld.argv", (long)getpid()) < 0) die("invalid audit path");
    child_path(path, dir, name);
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) die("cannot create argv receipt");
    char cwd[PATH_MAX];
    if (!getcwd(cwd, sizeof(cwd))) die("cannot resolve compiler working directory");
    for (int i = -2; i < argc; ++i) {
        const char *s = i == -2 ? event : (i == -1 ? cwd : argv[i]);
        size_t n = strlen(s) + 1;
        if (write(fd, s, n) != (ssize_t)n) die("cannot write argv receipt");
    }
    if (close(fd)) die("cannot close argv receipt");
}

int main(int argc, char **argv) {
    const char *signed_rustc = required("OHM_SOURCE_PASS_RUSTC");
    if (argc < 2 || !same_file(argv[1], signed_rustc)) die("unexpected rustc executable");
    if (getenv("LD_PRELOAD")) die("pre-existing preload");
    if (owner_codegen(argc, argv, required("OHM_SOURCE_PASS_WORKSPACE"))) {
        const char *dir = required("OHM_SOURCE_PASS_DIR");
        char path[PATH_MAX];
        child_path(path, dir, "mode");
        int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
        char mode[16] = {0};
        if (fd < 0) die("missing selection");
        ssize_t n = read(fd, mode, sizeof(mode));
        if (close(fd) || n <= 0 || n == (ssize_t)sizeof(mode)) die("invalid selection");
        if (!strcmp(mode, "plugin\n")) {
            child_path(path, dir, "loader.so");
            if (setenv("LD_PRELOAD", path, 1)) die("cannot set private preload");
            audit(argc, argv, "plugin");
        } else if (!strcmp(mode, "signed\n")) audit(argc, argv, "signed");
        else die("unknown selection");
    }
    execv(argv[1], argv + 1);
    die(strerror(errno));
}
