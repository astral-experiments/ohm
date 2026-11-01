/* Observe a private Cargo process tree. Only a signed, selected x86-64 rustc
 * at PTRACE_EVENT_EXEC may receive the extra, ordinary save-temps argument. */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <unistd.h>

#if !defined(__x86_64__) || !defined(__linux__)
#error The registered initial-stack ABI is Linux x86-64
#endif
_Static_assert(sizeof(uintptr_t) == 8, "unexpected target word size");

static const char flag[] = "-Csave-temps=yes";
static const char marker[] = "OHM_CGU_REQUEST=-Csave-temps=yes";
static int stage, capture, sequence;
static FILE *roster;
static struct stat compiler;

static void fail(const char *why) {
    fprintf(stderr, "CGU collector refused %s (%s)\n", why, strerror(errno));
    exit(125);
}

static void require(int ok, const char *why) { if (!ok) fail(why); }

static int procfile(pid_t pid, const char *leaf, int mode) {
    char path[90];
    int n = snprintf(path, sizeof(path), "/proc/%d/%s", pid, leaf);
    require(n > 0 && n < (int)sizeof(path), "proc path");
    int fd = open(path, mode | O_CLOEXEC);
    if (fd < 0) fail(leaf);
    return fd;
}

struct strings { char *buf; size_t len, count; };

static struct strings proc_strings(pid_t pid, const char *leaf) {
    int fd = procfile(pid, leaf, O_RDONLY);
    size_t cap = 4096, len = 0, count = 0;
    char *p = malloc(cap);
    require(p != NULL, "argument storage");
    for (;;) {
        if (len == cap) {
            require(cap < (4U << 20), "oversized exec payload");
            p = realloc(p, cap *= 2);
            require(p != NULL, "exec payload allocation");
        }
        ssize_t got = read(fd, p + len, cap - len);
        if (got < 0 && errno == EINTR) continue;
        require(got >= 0, "read proc payload");
        if (got == 0) break;
        len += (size_t)got;
    }
    require(!close(fd) && len && p[len - 1] == 0, "complete NUL payload");
    for (size_t i = 0; i < len; ++i) count += p[i] == 0;
    require(count <= 65536, "initial vector count");
    return (struct strings){p, len, count};
}

static const char *option(struct strings all, const char *key) {
    const char *result = "";
    for (char *p = all.buf; p < all.buf + all.len; p += strlen(p) + 1) {
        if (strcmp(p, key)) continue;
        char *v = p + strlen(p) + 1;
        require(!*result && v < all.buf + all.len, "duplicate or truncated argument");
        result = v;
    }
    return result;
}

static int contains(struct strings all, const char *key) {
    for (char *p = all.buf; p < all.buf + all.len; p += strlen(p) + 1) if (!strcmp(p, key)) return 1;
    return 0;
}

static void record(int dir, const char *name, const void *buf, size_t size) {
    int fd = openat(dir, name, O_WRONLY | O_EXCL | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) fail(name);
    const char *p = buf;
    for (size_t done = 0; done < size;) {
        ssize_t n = write(fd, p + done, size - done);
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, "write receipt");
        done += (size_t)n;
    }
    require(!close(fd), "close receipt");
}

static void memory(int fd, uintptr_t where, void *buf, size_t size, int writing) {
    char *p = buf;
    for (size_t done = 0; done < size;) {
        ssize_t n = writing ? pwrite(fd, p + done, size - done, (off_t)(where + done))
                            : pread(fd, p + done, size - done, (off_t)(where + done));
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, writing ? "write stopped initial stack" : "read stopped initial stack");
        done += (size_t)n;
    }
}

static void compare_string(int fd, uintptr_t ptr, const char *expected) {
    size_t n = strlen(expected) + 1;
    char *actual = malloc(n);
    require(ptr && actual, "initial string address");
    memory(fd, ptr, actual, n, 0);
    require(!memcmp(actual, expected, n), "kernel and userspace string values");
    free(actual);
}

static void selected(pid_t pid, struct strings args, const char *owner) {
    require(!mkdirat(stage, owner, 0700), "one selected invocation per owner and Cargo visit");
    int dir = openat(stage, owner, O_DIRECTORY | O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    require(dir >= 0, "own stage");
    record(dir, "original.nul", args.buf, args.len);
    struct strings env = proc_strings(pid, "environ");
    struct user_regs_struct regs;
    require(!ptrace(PTRACE_GETREGS, pid, NULL, &regs) && (regs.rsp % 16) == 0, "aligned exec-stop stack");
    int fd = procfile(pid, "mem", capture ? O_RDWR : O_RDONLY);
    size_t count = args.count + env.count + 3, bytes = count * sizeof(uintptr_t);
    uintptr_t *pre = malloc(bytes), *post = malloc(bytes), *checked = malloc(bytes);
    require(pre && post && checked, "initial vector allocation");
    memory(fd, regs.rsp, pre, bytes, 0);
    const size_t old_env = args.count + 2;
    require(pre[0] == args.count && pre[old_env - 1] == 0 && pre[count - 1] == 0, "original vector shape");
    size_t i = 1;
    for (char *p = args.buf; p < args.buf + args.len; p += strlen(p) + 1) compare_string(fd, pre[i++], p);
    size_t slot = count;
    i = old_env;
    for (char *p = env.buf; p < env.buf + env.len; p += strlen(p) + 1, ++i) {
        compare_string(fd, pre[i], p);
        if (!strcmp(p, marker)) { require(slot == count, "unique inert request"); slot = i; }
    }
    require(slot < count && !contains(args, flag), "request distinct from original compiler arguments");
    /* Keep the stack pointer, auxv address, and all pointed-to bytes intact.
     * The extra argv points to the flag suffix of this private environment string. */
    memcpy(post, pre, bytes);
    if (capture) {
        post[0]++;
        post[old_env - 1] = pre[slot] + sizeof("OHM_CGU_REQUEST=") - 1;
        post[old_env] = 0;
        for (size_t j = old_env; j < slot; ++j) post[j + 1] = pre[j];
    }
    uintptr_t aux_before[256], aux_after[256];
    size_t aux_words = 0;
    do {
        require(aux_words + 2 <= 256, "complete bounded auxiliary vector");
        memory(fd, regs.rsp + bytes + aux_words * sizeof(uintptr_t), &aux_before[aux_words], 2 * sizeof(uintptr_t), 0);
        aux_words += 2;
    } while (aux_before[aux_words - 2] != 0);
    if (capture) memory(fd, regs.rsp, post, bytes, 1);
    memory(fd, regs.rsp, checked, bytes, 0);
    memory(fd, regs.rsp + bytes, aux_after, aux_words * sizeof(uintptr_t), 0);
    require(!memcmp(post, checked, bytes) && !memcmp(aux_before, aux_after, aux_words * sizeof(uintptr_t)), "complete pointer and auxiliary vector readback");
    size_t env_pos = (size_t)checked[0] + 2;
    for (size_t j = old_env; j < count - 1; ++j) {
        if (capture && j == slot) continue;
        require(checked[env_pos++] == pre[j], "remaining environment order");
    }
    require(env_pos == count - 1 && checked[env_pos] == 0, "complete remaining environment");
    size_t observed_len = args.len + (capture ? sizeof(flag) : 0);
    char *observed = malloc(observed_len);
    require(observed != NULL, "observed arguments");
    size_t at = 0, ai = 1;
    for (char *p = args.buf; p < args.buf + args.len; p += strlen(p) + 1, ++ai) {
        size_t n = strlen(p) + 1; memory(fd, checked[ai], observed + at, n, 0); at += n;
    }
    require(!memcmp(observed, args.buf, args.len), "ordinary argv retained");
    if (capture) {
        memory(fd, checked[ai], observed + at, sizeof(flag), 0);
        require(!memcmp(observed + at, flag, sizeof(flag)), "actual saved-temp argument");
    }
    record(dir, "observed.nul", observed, observed_len);
    char info[512];
    int n = snprintf(info, sizeof(info), "{\"pid\":%d,\"compiler_dev\":%ju,\"compiler_ino\":%ju,\"capture\":%s,\"argc\":[%zu,%" PRIuPTR "],\"envc\":[%zu,%zu],\"aux_pairs\":%zu}\n", pid, (uintmax_t)compiler.st_dev, (uintmax_t)compiler.st_ino, capture ? "true" : "false", args.count, checked[0], env.count, env.count - (size_t)capture, aux_words / 2);
    require(n > 0 && n < (int)sizeof(info), "bounded process receipt");record(dir, "process.json", info, (size_t)n);
    require(!close(fd) && !close(dir), "close selected process");
    free(observed);free(pre);free(post);free(checked);free(env.buf);
}

static void on_exec(pid_t pid) {
    int exe = procfile(pid, "exe", O_PATH);
    struct stat st;
    require(!fstat(exe, &st) && !close(exe), "physical exec");
    if (st.st_dev != compiler.st_dev || st.st_ino != compiler.st_ino) return;
    struct strings args = proc_strings(pid, "cmdline");
    const char *owner = option(args, "--crate-name");
    for (const char *p = owner; *p; ++p) require(isalnum((unsigned char)*p) || *p == '_', "unrecognized rustc crate name");
    char name[40]; snprintf(name, sizeof(name), "rustc-%05d.nul", ++sequence);
    record(stage, name, args.buf, args.len);
    fprintf(roster, "{\"seq\":%d,\"pid\":%d,\"crate\":\"%s\",\"entry\":\"%s\"}\n", sequence, pid, owner, name);
    if ((!strcmp(owner, "ruff_linter") || !strcmp(owner, "ruff_workspace")) &&
        !strcmp(option(args, "--crate-type"), "lib") && *option(args, "--out-dir") && contains(args, "--emit=dep-info,metadata,link")) selected(pid, args, owner);
    free(args.buf);
}

static void resume(pid_t pid, int sig) {
    if (ptrace(PTRACE_CONT, pid, NULL, sig) < 0 && errno != ESRCH) fail("resume tracee");
}

int main(int argc, char **argv) {
    require(argc >= 5 && (!strcmp(argv[3], "capture") || !strcmp(argv[3], "observe")), "STAGE SIGNED_RUSTC observe|capture PROGRAM [ARGS]");
    capture = !strcmp(argv[3], "capture");
    require(!getenv("LD_PRELOAD") && !getenv("RUSTC_WRAPPER") && !getenv("RUSTC_WORKSPACE_WRAPPER") && !getenv("RUSTFLAGS") && !getenv("CARGO_ENCODED_RUSTFLAGS"), "ordinary Cargo authentication environment");
    require(getenv("OHM_CGU_REQUEST") && !strcmp(getenv("OHM_CGU_REQUEST"), flag), "enrolled request slot");
    stage = open(argv[1], O_DIRECTORY | O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    require(stage >= 0 && !stat(argv[2], &compiler) && S_ISREG(compiler.st_mode), "private stage and signed selector");
    int log_fd = openat(stage, "rustc.jsonl", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    require(log_fd >= 0 && (roster = fdopen(log_fd, "w")) != NULL, "open rustc roster");
    setvbuf(roster, NULL, _IOLBF, 0);
    pid_t root = fork();require(root >= 0, "fork Cargo");
    if (root == 0) {
        if (ptrace(PTRACE_TRACEME, 0, NULL, NULL) != 0) _exit(122);
        raise(SIGSTOP);execvp(argv[4], argv + 4);_exit(127);
    }
    int status, code = -1;
    require(waitpid(root, &status, 0) == root && WIFSTOPPED(status) && WSTOPSIG(status) == SIGSTOP, "initial stop");
    long opts = PTRACE_O_TRACEFORK | PTRACE_O_TRACEVFORK | PTRACE_O_TRACECLONE | PTRACE_O_TRACEEXEC | PTRACE_O_EXITKILL;
    require(!ptrace(PTRACE_SETOPTIONS, root, NULL, opts), "trace private tree");resume(root, 0);
    for (;;) {
        pid_t pid = waitpid(-1, &status, __WALL);
        if (pid < 0 && errno == EINTR) continue;
        if (pid < 0 && errno == ECHILD) break;
        require(pid > 0, "wait for child");
        if (WIFEXITED(status) || WIFSIGNALED(status)) {
            if (pid == root) code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
            continue;
        }
        require(WIFSTOPPED(status), "unexpected child status");
        unsigned event = (unsigned)status >> 16;
        if (event == PTRACE_EVENT_EXEC) on_exec(pid);
        else require(!event || event == PTRACE_EVENT_FORK || event == PTRACE_EVENT_VFORK || event == PTRACE_EVENT_CLONE, "unexpected ptrace event");
        int signal = WSTOPSIG(status);
        resume(pid, (event || signal == SIGSTOP) ? 0 : signal);
    }
    require(code >= 0 && !fclose(roster) && !close(stage), "complete child and rustc roster");return code;
}
