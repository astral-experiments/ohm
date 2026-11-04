/* Capture only selected signed Wild execs. The original process is stopped, never rewritten. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
static int stage;
static struct stat linker;
static const char *reader, *public_dir, *private_dir;
static FILE *names;
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


static void captured_fds(pid_t pid, int output) {
    char name[128], target[PATH_MAX+1];
    snprintf(name,sizeof(name),"/proc/%d/fd",pid);
    DIR *dir=opendir(name);require(dir!=NULL,"original FD directory");
    int desc=openat(output,"fds",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    FILE *f=desc>=0?fdopen(desc,"w"):NULL;require(f!=NULL,"private FD log");
    struct dirent *entry;
    while ((entry=readdir(dir))) {
        char *end=NULL;
        long n=strtol(entry->d_name,&end,10);
        if (*end || n<3)continue;
        int k=snprintf(name,sizeof(name),"/proc/%d/fd/%ld",pid,n);
        require(k>0 && k<(int)sizeof(name),"original FD");
        ssize_t len=readlink(name,target,sizeof(target)-1);
        require(len>0 && len<(ssize_t)sizeof(target)-1,"original FD target");target[len]=0;
        if (strncmp(target,"pipe:[",6))continue;
        int fd=open(name,O_RDONLY|O_NONBLOCK|O_CLOEXEC),bytes=0;
        require(fd>=0 && ioctl(fd,FIONREAD,&bytes)==0 && !close(fd) && bytes>=0,"available pipe bytes");
        require(fprintf(f,"%ld %d %s\n",n,bytes,target)>0,"write pipe binding");
    }
    require(!closedir(dir)&&!fclose(f),"finish original FD inventory");
}
static int selected(const char *name) {
    char line[512];rewind(names);
    while (fgets(line,sizeof(line),names)) {
        line[strcspn(line,"\n")]=0;
        if (!strcmp(line,name)) return 1;
    }
    require(!ferror(names),"read selection");
    return 0;
}
static void on_exec(pid_t pid) {
    int fd=procfile(pid,"exe",O_RDONLY);
    struct stat st;require(!fstat(fd,&st) && !close(fd),"observed executable identity");
    if (st.st_dev!=linker.st_dev||st.st_ino!=linker.st_ino)return;
    struct strings args=proc_strings(pid,"cmdline");
    const char *output=option(args,"-o");const char *name=strrchr(output,'/');name=name?name+1:output;
    if (!selected(name)){free(args.buf);return;}
    require(!strchr(name,'/') && !mkdirat(stage,name,0700),"unique selected Wild exec");
    int dir=openat(stage,name,O_DIRECTORY|O_RDONLY|O_NOFOLLOW|O_CLOEXEC);require(dir>=0,"private capture");
    struct strings env=proc_strings(pid,"environ");
    record(dir,"argv.nul",args.buf,args.len);record(dir,"env.nul",env.buf,env.len);
    char link[80],cwd[PATH_MAX];snprintf(link,sizeof(link),"/proc/%d/cwd",pid);ssize_t n=readlink(link,cwd,sizeof(cwd));
    require(n>0 && n<(ssize_t)sizeof(cwd),"original linker cwd");record(dir,"cwd",cwd,(size_t)n);
    captured_fds(pid,dir);require(!close(dir),"close capture");
    pid_t worker=fork();require(worker>=0,"start independent linker reader");
    if (!worker){execl("/usr/bin/python3","python3","-IB",reader,private_dir,public_dir,name,(char *)NULL);_exit(127);}
    int status=0;pid_t done;
    do {done=waitpid(worker,&status,0);} while(done<0 && errno==EINTR);
    require(done==worker,"standalone linker readback terminated");
    int logdir=open(public_dir,O_DIRECTORY|O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    require(logdir>=0,"public completion directory");
    char mark[600],result[96];
    int key=snprintf(mark,sizeof(mark),"readback-%s.status",name);
    int nres=snprintf(result,sizeof(result),"%d %d\n",WIFEXITED(status),WIFEXITED(status)?WEXITSTATUS(status):-1);
    require(key>0 && key<(int)sizeof(mark) && nres>0 && nres<(int)sizeof(result),"status representation");
    record(logdir,mark,result,(size_t)nres);
    require(!close(logdir),"close status");
    // Let the unmodified linker complete even if its independent observational replay refused.
    // The Python reader rejects any nonzero recorded child status after all native controls finish.
    free(args.buf);free(env.buf);
}
static void resume(pid_t pid, int sig) {
    if (ptrace(PTRACE_CONT, pid, NULL, sig) < 0 && errno != ESRCH) fail("resume tracee");
}


int main(int argc,char **argv) {
    require(argc>=7,"PRIVATE PUBLIC NAMES SIGNED_WILD READER PROGRAM [ARG...]");
    private_dir=argv[1];public_dir=argv[2];reader=argv[5];
    require(!getenv("LD_PRELOAD")&&!getenv("RUSTC_WRAPPER")&&!getenv("RUSTFLAGS")&&!getenv("CARGO_ENCODED_RUSTFLAGS")&&!getenv("GH_TOKEN")&&!getenv("GITHUB_TOKEN"), "ordinary private Cargo environment");
    stage=open(private_dir,O_DIRECTORY|O_RDONLY|O_NOFOLLOW|O_CLOEXEC);names=fopen(argv[3],"re");
    require(stage>=0 && names && !stat(argv[4],&linker) && S_ISREG(linker.st_mode),"stage and signed ELF");
    pid_t root = fork();require(root >= 0, "fork Cargo");
    if (root == 0) {
        if (ptrace(PTRACE_TRACEME, 0, NULL, NULL) != 0) _exit(122);
        raise(SIGSTOP);execvp(argv[6], argv + 6);_exit(127);
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
    require(code >= 0 && !fclose(names) && !close(stage), "complete child and selected Wild roster");return code;
}
