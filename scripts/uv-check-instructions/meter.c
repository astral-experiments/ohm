#define _GNU_SOURCE
#include <err.h>
#include <errno.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

// Open a counter on each rustc image before the dynamic loader runs.
// The kernel sums the threads of that image, excluding forked processes.
struct image {
    struct image *next;
    char *crate;
    char *kind;
    int fd;
    pid_t pid;
};

static struct image *images;
static struct stat selected;

static void read_args(struct image *image) {
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/cmdline", image->pid);
    FILE *f = fopen(path, "r");
    if (!f) err(1, "%s", path);
    char *arg = NULL;
    size_t size = 0;
    while (getdelim(&arg, &size, 0, f) > 0) {
        char **slot = NULL;
        if (!strcmp(arg, "--crate-name")) slot = &image->crate;
        if (!strcmp(arg, "--crate-type")) slot = &image->kind;
        if (!slot) continue;
        if (getdelim(&arg, &size, 0, f) < 0 || strpbrk(arg, "\t\n"))
            errx(1, "invalid crate argument");
        free(*slot);
        *slot = strdup(arg);
        if (!*slot) err(1, "strdup");
    }
    if (ferror(f)) err(1, "%s", path);
    free(arg);
    fclose(f);
}

static void observe_exec(pid_t pid) {
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/exe", pid);
    struct stat exe;
    if (stat(path, &exe)) err(1, "%s", path);
    if (exe.st_dev != selected.st_dev || exe.st_ino != selected.st_ino)
        return;
    struct perf_event_attr attr = {
        .type = PERF_TYPE_HARDWARE,
        .size = sizeof(attr),
        .config = PERF_COUNT_HW_INSTRUCTIONS,
        .exclude_kernel = 1,
        .exclude_hv = 1,
        .inherit = 1,
        .inherit_thread = 1,
        .remove_on_exec = 1,
        .read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    int fd = syscall(SYS_perf_event_open, &attr, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    if (fd < 0) err(1, "perf_event_open for pid %d", pid);
    struct image *image = calloc(1, sizeof(*image));
    if (!image) err(1, "calloc");
    image->fd = fd;
    image->pid = pid;
    image->next = images;
    images = image;
    read_args(image);
}

static void resume(pid_t pid, int sig) {
    if (ptrace(PTRACE_CONT, pid, NULL, (void *)(long)sig) && errno != ESRCH)
        err(1, "PTRACE_CONT");
}

static int trace(char **argv) {
    pid_t root = fork();
    if (root == -1) err(1, "fork");
    if (!root) {
        if (ptrace(PTRACE_TRACEME, 0, NULL, NULL)) err(1, "PTRACE_TRACEME");
        raise(SIGSTOP);
        execvp(argv[0], argv);
        err(1, "execvp");
    }
    int status;
    if (waitpid(root, &status, 0) != root || !WIFSTOPPED(status))
        errx(1, "child failed to start");
    long opts = PTRACE_O_TRACEEXEC | PTRACE_O_TRACEFORK | PTRACE_O_TRACEVFORK
        | PTRACE_O_TRACECLONE | PTRACE_O_EXITKILL;
    if (ptrace(PTRACE_SETOPTIONS, root, NULL, (void *)opts))
        err(1, "PTRACE_SETOPTIONS");
    resume(root, 0);
    int code = 1;
    for (;;) {
        pid_t pid = waitpid(-1, &status, __WALL);
        if (pid == -1) {
            if (errno == ECHILD) break;
            if (errno == EINTR) continue;
            err(1, "waitpid");
        }
        if (WIFSTOPPED(status)) {
            int event = status >> 16;
            if (event == PTRACE_EVENT_EXEC) observe_exec(pid);
            int sig = WSTOPSIG(status);
            resume(pid, event || sig == SIGSTOP ? 0 : sig);
        } else if (pid == root && WIFEXITED(status)) {
            code = WEXITSTATUS(status);
        }
    }
    return code;
}

int main(int argc, char **argv) {
    if (argc < 4) errx(1, "usage: meter executable receipt command [arg...]");
    if (stat(argv[1], &selected)) err(1, "%s", argv[1]);
    int code = trace(argv + 3);
    FILE *out = fopen(argv[2], "wx");
    if (!out) err(1, "%s", argv[2]);
    for (struct image *i = images; i; i = i->next) {
        struct { uint64_t instructions, enabled, running; } value;
        if (read(i->fd, &value, sizeof(value)) != sizeof(value))
            errx(1, "could not read counter for pid %d", i->pid);
        close(i->fd);
        if (!value.instructions || !value.running || value.running > value.enabled
            || value.running < value.enabled * .995)
            errx(1, "unusable PMU for pid %d: %" PRIu64 " instructions, %" PRIu64 "/%" PRIu64 " ns",
                 i->pid, value.instructions, value.running, value.enabled);
        fprintf(out, "%d\t%s\t%s\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",
                i->pid, i->crate ? i->crate : "-", i->kind ? i->kind : "-",
                value.instructions, value.running, value.enabled);
    }
    if (ferror(out) || fclose(out)) err(1, "receipt");
    return code;
}
