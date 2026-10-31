// Reuse the SHA-bound process observer's event ABI, file and /proc helpers.
#define main previous_gnu_process_observer
#include "observer.c"
#undef main

struct worker {
    pid_t tid;
    int fd;
    int saw_exit;
    int waited;
};
static struct worker workers[512];
static unsigned worker_count;

static struct worker *lookup(pid_t tid) {
    for (unsigned i = 0; i < worker_count; i++) {
        if (workers[i].tid == tid) return &workers[i];
    }
    return NULL;
}

static int worker_event(pid_t pid, int inherit, int count) {
    if (!count) return -1;
    struct perf_event_attr a = spec(0);
    a.inherit = inherit;
    int fd = syscall(SYS_perf_event_open, &a, pid, -1, -1, PERF_FLAG_FD_CLOEXEC);
    if (fd < 0) fatal("perf_event_open worker");
    if (ioctl(fd, PERF_EVENT_IOC_ENABLE, 0)) fatal("enable worker event");
    return fd;
}

static void register_worker(pid_t tid, int count) {
    need(worker_count < 512 && !lookup(tid), "duplicate or excessive worker");
    workers[worker_count++] = (struct worker){.tid=tid, .fd=worker_event(tid, 0, count)};
}

static int get_group(pid_t tid) {
    char path[80], *line = NULL;
    size_t size = 0;
    snprintf(path, sizeof(path), "/proc/%d/status", tid);
    FILE *s = fopen(path, "r");
    if (!s) fatal("open /proc status");
    int group = 0;
    while (getline(&line, &size, s) >= 0) {
        if (sscanf(line, "Tgid:%d", &group) == 1) break;
    }
    free(line);
    if (fclose(s)) fatal("close /proc status");
    need(group > 0, "missing Tgid");
    return group;
}

static void thread_name(pid_t tid, char *out, size_t size) {
    char path[80];
    snprintf(path, sizeof(path), "/proc/%d/comm", tid);
    FILE *f = fopen(path, "r");
    if (!f || !fgets(out, size, f)) fatal("open or read terminal comm");
    size_t n = strlen(out);
    need(n > 1 && n <= 16 && out[n-1] == '\n' && fgetc(f) == EOF, "terminal comm format");
    out[--n] = 0;
    for (size_t i = 0; i < n; i++) need(out[i] >= ' ' && out[i] <= '~', "unsafe comm byte");
    if (fclose(f)) fatal("close terminal comm");
}

static int unit_argument(const char *args, size_t len, const char *key, const char *expected) {
    int matches = 0, seen = 0;
    for (const char *v = args; v < args + len; v += strlen(v) + 1) {
        if (strcmp(v, key)) continue;
        const char *value = v + strlen(v) + 1;
        need(value < args + len && !seen++, "missing or duplicate compiler option");
        matches = !strcmp(value, expected);
    }
    return matches;
}

static void close_event(FILE *out, const char *kind, pid_t tid, int fd) {
    uint64_t v[3] = {0};
    if (fd >= 0) {
        need(read(fd, v, sizeof(v)) == (ssize_t)sizeof(v), "incomplete perf read");
        if (close(fd)) fatal("close perf event");
    }
    fprintf(out, "%s\t%d\t%d\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",
            kind, tid, fd >= 0, v[0], v[1], v[2]);
}

int main(int argc, char **argv) {
    need(argc >= 6, "OUT topology|hardware RUSTC CRATE COMMAND ...");
    const char *outdir=argv[1], *mode=argv[2], *crate_name=argv[4];
    int count = !strcmp(mode, "hardware");
    need(count || !strcmp(mode, "topology"), "bad mode");
    struct stat compiler;
    if (stat(argv[3], &compiler)) fatal("stat compiler");
    FILE *log=file(outdir, "events.tsv"), *raw=file(outdir, "samples.tsv");
    for (int inherit = 0; inherit <= 2; inherit++) {
        struct perf_event_attr a = spec(inherit == 2);
        a.inherit = inherit != 0;
        FILE *f = file(outdir, inherit == 2 ? "whole.attr" : inherit ? "group.attr" : "thread.attr");
        need(fwrite(&a, 1, sizeof(a), f) == sizeof(a) && !fclose(f), "save perf ABI");
    }
    pid_t root = fork();
    if (root < 0) fatal("fork command");
    if (!root) {
        if (ptrace(PTRACE_TRACEME, 0, 0, 0) || raise(SIGSTOP)) _exit(125);
        execvp(argv[5], &argv[5]); _exit(126);
    }
    int status, result = -1;
    need(waitpid(root, &status, 0) == root && WIFSTOPPED(status) && WSTOPSIG(status)==SIGSTOP,
         "initial command stop");
    long flags=PTRACE_O_EXITKILL | PTRACE_O_TRACECLONE | PTRACE_O_TRACEFORK | PTRACE_O_TRACEVFORK |
               PTRACE_O_TRACEEXEC | PTRACE_O_TRACEEXIT;
    if (ptrace(PTRACE_SETOPTIONS, root, 0, flags)) fatal("ptrace options");
    int whole_fd=-1;
    if (count) {
        whole_fd=event(root, 1);
        if (whole_fd<0) fatal("whole event");
    }
    pid_t group = 0;
    int group_fd = -1;
    fprintf(log, "root\t%d\n", root);
    resume(root,0);
    for (;;) {
        pid_t tid = waitpid(-1, &status, __WALL);
        if (tid < 0 && errno == EINTR) continue;
        if (tid < 0 && errno == ECHILD) break;
        if (tid < 0) fatal("wait kernel");
        struct worker *row=lookup(tid);
        if (WIFEXITED(status) || WIFSIGNALED(status)) {
            int code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
            fprintf(log, "wait\t%d\t%d\n", tid, code);
            if (tid == root) result=code;
            if (row) {
                need(row->saw_exit && !row->waited && !code, "unobserved or failed worker");
                row->waited = 1;
            }
            continue;
        }
        need(WIFSTOPPED(status), "non-stop status");
        unsigned e=(unsigned)status >> 16;
        int sig=WSTOPSIG(status);
        if (e == PTRACE_EVENT_EXEC) {
            char path[80]; struct stat physical;
            snprintf(path,sizeof(path),"/proc/%d/exe",tid);
            if (stat(path, &physical)) fatal("stat exec");
            int selected=0;
            if (same(physical, compiler)) {
                size_t len; char *args=argv_at_exec(tid,&len);
                selected=unit_argument(args,len,"--crate-name",crate_name) && arg(args,len,"--out-dir");
                if (selected) {
                    need(!group && get_group(tid)==tid, "second matching unit or nonleader");
                    group=tid;
                    group_fd=worker_event(tid,1,count);
                    register_worker(tid,count);
                    FILE *f=file(outdir,"selected.argv");
                    need(fwrite(args,1,len,f)==len && !fclose(f), "save selected argv");
                }
                free(args);
            }
            fprintf(log,"exec\t%d\t%ju\t%ju\t%d\n",tid,(uintmax_t)physical.st_dev,
                    (uintmax_t)physical.st_ino,selected);
        } else if (e==PTRACE_EVENT_CLONE || e==PTRACE_EVENT_FORK || e==PTRACE_EVENT_VFORK) {
            unsigned long child;
            if (ptrace(PTRACE_GETEVENTMSG,tid,0,&child)) fatal("get new task");
            fprintf(log,"spawn\t%d\t%lu\t%u\n",tid,child,e);
        } else if (e==PTRACE_EVENT_EXIT) {
            unsigned long exit_status;
            if (ptrace(PTRACE_GETEVENTMSG,tid,0,&exit_status)) fatal("get kernel exit");
            if (row) {
                char name[64]; thread_name(tid,name,sizeof(name));
                need(!row->saw_exit && get_group(tid)==group && exit_status==0, "worker exit");
                row->saw_exit=1;
                fprintf(log,"name\t%d\t%d\t%lu\t%s\n",tid,group,exit_status,name);
            }
        } else if (!e && sig==SIGSTOP) {
            int tgid=get_group(tid);
            fprintf(log,"born\t%d\t%d\n",tid,tgid);
            if (group && tgid==group) register_worker(tid,count);
        } else {
            need(!e, "unhandled ptrace event");
        }
        resume(tid,(e || sig==SIGSTOP)?0:sig);
    }
    need(result == 0 && group && worker_count>0, "missing or failed selected compiler");
    for (unsigned i=0; i<worker_count; i++) {
        need(workers[i].saw_exit && workers[i].waited, "unclosed worker");
        close_event(raw,"task",workers[i].tid,workers[i].fd);
    }
    close_event(raw,"compiler",group,group_fd);
    close_event(raw,"command",root,whole_fd);
    need(!fclose(log) && !fclose(raw), "flush records");
    return result;
}
