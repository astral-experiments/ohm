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
#include <time.h>
#include <sys/resource.h>

// Open a counter on each rustc image before the dynamic loader runs.
// The kernel sums the threads of that image, excluding forked processes.
struct image {
    double start,elapsed,cpu;
    struct image *next;
    char *crate;
    char *kind;
    int fd;
    pid_t pid;
};

static struct image *images;
static struct stat selected, clippy;
static int tree_fd = -1;

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

static double seconds(void) {
    struct timespec stamp;
    if (clock_gettime(CLOCK_MONOTONIC,&stamp)) err(1,"clock");
    return stamp.tv_sec + stamp.tv_nsec*1e-9;
}

static void observe_exec(pid_t pid) {
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/exe", pid);
    struct stat exe;
    if (stat(path, &exe)) err(1, "%s", path);
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
    if (tree_fd == -1) {
        // At the root exec, count Cargo and all descendants independently of
        // the rustc/clippy-driver image totals, excluding this tracer.
        struct perf_event_attr tree = attr;
        tree.inherit_thread = tree.remove_on_exec = 0;
        tree_fd = syscall(SYS_perf_event_open, &tree, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
        if (tree_fd < 0) err(1, "tree counter");
    }
    char full[4096];
    ssize_t len = readlink(path, full, sizeof full-1);
    if (len < 0) err(1,"readlink");
    full[len] = 0;
    char *name = strrchr(full,'/');
    name = name ? name + 1 : full;
    int test = !strncmp(name,"pip_install-",12)
        || !strncmp(name,"uv_client-",10)
        || !strncmp(name,"uv_pypi_types-",14);
    if (test) attr.inherit_thread = attr.remove_on_exec = 0;
    if (!test && (exe.st_dev != selected.st_dev || exe.st_ino != selected.st_ino) &&
        (exe.st_dev != clippy.st_dev || exe.st_ino != clippy.st_ino)) return;
    int fd = syscall(SYS_perf_event_open, &attr, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    if (fd < 0) err(1, "perf_event_open for pid %d", pid);
    struct image *image = calloc(1, sizeof(*image));
    if (!image) err(1, "calloc");
    image->fd = fd;
    image->pid = pid;
    image->next = images;
    images = image;
    image->start = seconds();
    if (test) {
        image->kind = strdup("test-tree");
        image->crate = strdup(name);
    } else read_args(image);
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
        struct rusage usage;
        pid_t pid = wait4(-1, &status, __WALL, &usage);
        if (pid > 0 && WIFEXITED(status)) {
            for (struct image *i=images;i;i=i->next) {
                if (i->pid!=pid) continue;
                i->elapsed=seconds()-i->start;
                i->cpu=usage.ru_utime.tv_sec+usage.ru_stime.tv_sec
                    + (usage.ru_utime.tv_usec+usage.ru_stime.tv_usec)*1e-6;
                break;
            }
        }
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
    const char *driver = getenv("MEASURE_CLIPPY");
    if (driver && stat(driver, &clippy)) err(1, "%s", driver);
    int code = trace(argv + 3);
    struct { uint64_t instructions, enabled, running; } v;
    if (read(tree_fd, &v, sizeof(v)) != sizeof(v) ||
        !v.instructions || !v.running || v.running > v.enabled || v.running < v.enabled * .995)
        errx(1, "unusable tree counter");
    char *filename;
    if (asprintf(&filename, "%s.tree", argv[2]) < 0) err(1, "asprintf");
    FILE *tree = fopen(filename, "wx");
    if (!tree) err(1, "%s", filename);
    fprintf(tree, "%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n", v.instructions, v.enabled, v.running);
    if (ferror(tree) || fclose(tree)) err(1, "tree receipt");
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
        fprintf(out, "%d\t%s\t%s\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\t%.9f\t%.9f\n",
                i->pid, i->crate ? i->crate : "-", i->kind ? i->kind : "-",
                value.instructions, value.enabled, value.running, i->elapsed, i->cpu);
    }
    if (ferror(out) || fclose(out)) err(1, "receipt");
    return code;
}

