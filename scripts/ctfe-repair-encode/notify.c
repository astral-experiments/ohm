/* Unscored Linux x86-64 QA. No loader injection and no product wrapper. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/openat2.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

static pid_t subject;
static void need(bool ok, const char *why) {
  if (ok)
    return;
  int err = errno;
  if (subject > 0)
    kill(-subject, SIGKILL);
  fprintf(stderr, "selective notifier refusal: %s (errno %d)\n", why, err);
  exit(125);
}
static bool same(const struct stat *a, const struct stat *b) {
  return a->st_dev == b->st_dev && a->st_ino == b->st_ino &&
         a->st_size == b->st_size && a->st_mode == b->st_mode &&
         a->st_mtim.tv_sec == b->st_mtim.tv_sec &&
         a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
         a->st_ctim.tv_sec == b->st_ctim.tv_sec &&
         a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
}
static int proc_open(pid_t tid, const char *name) {
  char path[80];
  snprintf(path, sizeof(path), "/proc/%d/%s", tid, name);
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  need(fd >= 0, "read requested /proc file");
  return fd;
}
enum { RUSTC = 1, CARGO, WILD, DRIVER, MAX_OWNERS = 32 };
static const char *const roles[] = {"", "rustc", "cargo", "wild", "driver"};
static const char *const members[] = {
    "", "bin/rustc", "bin/cargo",
    "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd",
    "lib/librustc_driver-c5276fb6f0cdddb4.so"};
static struct {
  char path[PATH_MAX];
  int fd;
  struct stat st;
} files[5];
static char roots[MAX_OWNERS][PATH_MAX], ctl[PATH_MAX];
static int nroots;
static bool deny;

static void fmt(char *buf, size_t n, const char *s, ...) {
  va_list v;
  va_start(v, s);
  int w = vsnprintf(buf, n, s, v);
  va_end(v);
  need(w >= 0 && (size_t)w < n, "native path length");
}
static void fetchlink(const char *p, char *buf, size_t n) {
  ssize_t k = readlink(p, buf, n);
  need(k > 0 && (size_t)k < n, "read native symlink");
  buf[k] = 0;
}
static FILE *newlog(const char *name, const char *mode) {
  char dest[PATH_MAX];
  fmt(dest, sizeof(dest), "%s/%s", ctl, name);
  FILE *f = fopen(dest, mode);
  need(f != NULL, "private evidence file");
  return f;
}
static void finishlog(FILE *f) {
  need(!ferror(f) && fclose(f) == 0, "evidence write");
}
static void copy_proc(pid_t p, const char *role, const char *kind) {
  int fd = proc_open(p, kind);
  char name[100], buf[8192];
  fmt(name, sizeof(name), "%s-%d.%s", role, p, kind);
  FILE *o = newlog(name, "wxe");
  ssize_t n;
  while ((n = read(fd, buf, sizeof(buf))) > 0)
    need(fwrite(buf, 1, n, o) == (size_t)n, "proc evidence write");
  need(n == 0 && close(fd) == 0, "proc evidence read");
  finishlog(o);
}
static void table_init(const char *control, const char *sdk) {
  char abs[PATH_MAX], line[PATH_MAX + 3];
  need(realpath(control, abs) && !strcmp(abs, control) && realpath(sdk, abs) &&
           !strcmp(abs, sdk),
       "noncanonical subjects");
  fmt(ctl, sizeof(ctl), "%s", control);
  FILE *f = newlog("config", "re");
  need(fgets(line, sizeof(line), f) &&
           (!strcmp(line, "P\n") || !strcmp(line, "B\n")),
       "mode");
  deny = line[0] == 'B';
  while (fgets(line, sizeof(line), f)) {
    size_t n = strlen(line);
    need(n > 1 && line[n - 1] == '\n' && !strchr(line, '\t') &&
             nroots < MAX_OWNERS,
         "imprecise owner");
    line[n - 1] = 0;
    need(realpath(line, abs) && !strcmp(abs, line), "unverified owner");
    for (int i = 0; i < nroots; i++)
      need(strcmp(roots[i], line) != 0, "duplicate owner");
    fmt(roots[nroots++], PATH_MAX, "%s", line);
  }
  need(nroots > 0 && !ferror(f) && fclose(f) == 0, "empty/incomplete config");
  for (int i = 1; i <= DRIVER; i++) {
    fmt(files[i].path, PATH_MAX, "%s/%s", sdk, members[i]);
    need(realpath(files[i].path, abs) && !strcmp(abs, files[i].path),
         "noncanonical SDK member");
    files[i].fd = open(abs, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    need(files[i].fd >= 0 && fstat(files[i].fd, &files[i].st) == 0 &&
             S_ISREG(files[i].st.st_mode),
         "SDK filename/descriptor");
  }
  /* The read-only one-page mapping of the held SDK descriptor positively binds
     overlay st_dev to the kernel's backing-map device. It cannot stand in for
     the tracee's separate successful executable mmap, recorded below. */
  void *addr = mmap(NULL, 4096, PROT_READ, MAP_PRIVATE, files[DRIVER].fd, 0);
  need(addr != MAP_FAILED, "map reference");
  f = fopen("/proc/self/maps", "re");
  need(f != NULL, "reference maps");
  FILE *o = newlog("driver.reference", "wxe");
  fprintf(o, "%ju\t%ju\t%jd\t%jx\n", (uintmax_t)files[DRIVER].st.st_dev,
          (uintmax_t)files[DRIVER].st.st_ino,
          (intmax_t)files[DRIVER].st.st_size, (uintmax_t)(uintptr_t)addr);
  int count = 0;
  char *buf = NULL;
  size_t cap = 0;
  while (getline(&buf, &cap, f) > 0) {
    unsigned long a, b;
    if (sscanf(buf, "%lx-%lx", &a, &b) == 2 && (uintptr_t)addr >= a &&
        (uintptr_t)addr < b) {
      fputs(buf, o);
      count++;
    }
  }
  need(count == 1 && !ferror(f) && fclose(f) == 0 && !munmap(addr, 4096),
       "reference mapping");
  free(buf);
  finishlog(o);
}
static void table_finish(void) {
  for (int i = 1; i <= DRIVER; i++) {
    struct stat a, b;
    need(!fstat(files[i].fd, &a) && !stat(files[i].path, &b) && same(&a, &b) &&
             same(&a, &files[i].st),
         "enrolled member changed");
    need(!close(files[i].fd), "close enrolled member");
  }
}
/* Notifications for executable mappings attest the real image after exec. Exact
   exec count is independently checked against strace's successful exec returns.
 */
struct process {
  pid_t pid;
  int role;
  bool mapped, pending;
};
static struct process watched[2048];
static size_t nwatch;
static int allfd[64], selected[64], nall;
static char allroots[64][PATH_MAX];
static int listener;
static unsigned continued, injected, denied;
static pid_t attempted[8192];
static size_t nattempt;
static pid_t group_id(pid_t tid) {
  char path[64], line[256];
  fmt(path, sizeof(path), "/proc/%d/status", tid);
  FILE *f = fopen(path, "re");
  need(f != NULL, "visible process group");
  int tgid = 0;
  while (fgets(line, sizeof(line), f)) {
    if (sscanf(line, "Tgid: %d", &tgid) == 1)
      break;
  }
  need(tgid > 0 && !fclose(f), "true thread group");
  return tgid;
}
static void owners(void) {
  FILE *in = newlog("owners", "re");
  char line[PATH_MAX + 2], canonical[PATH_MAX];
  int ns = 0;
  while (fgets(line, sizeof(line), in)) {
    size_t n = strlen(line);
    need(n > 1 && line[n - 1] == '\n' && nall < 64, "all owner list");
    line[n - 1] = 0;
    need(realpath(line, canonical) && !strcmp(canonical, line),
         "actual owner path");
    for (int k = 0; k < nall; k++)
      need(strcmp(allroots[k], line) != 0, "duplicate all owner");
    fmt(allroots[nall], PATH_MAX, "%s", line);
    allfd[nall] = open(line, O_DIRECTORY | O_PATH | O_CLOEXEC | O_NOFOLLOW);
    need(allfd[nall] >= 0, "hold real owner");
    selected[nall] = -1;
    for (int k = 0; k < nroots; k++)
      if (!strcmp(roots[k], line)) {
        selected[nall] = k;
        ns++;
      }
    nall++;
  }
  need(ns == nroots && !ferror(in) && !fclose(in),
       "missing selected physical owner");
}
static void send_fd(int sock, int fd) {
  char b = 'L', c[CMSG_SPACE(sizeof(fd))] = {0};
  struct iovec iov = {&b, 1};
  struct msghdr m = {.msg_iov = &iov,
                     .msg_iovlen = 1,
                     .msg_control = c,
                     .msg_controllen = sizeof(c)};
  struct cmsghdr *h = CMSG_FIRSTHDR(&m);
  h->cmsg_level = SOL_SOCKET;
  h->cmsg_type = SCM_RIGHTS;
  h->cmsg_len = CMSG_LEN(sizeof(fd));
  memcpy(CMSG_DATA(h), &fd, sizeof(fd));
  need(sendmsg(sock, &m, 0) == 1, "send listener");
}
static int receive_fd(int sock) {
  int fd;
  char b, c[CMSG_SPACE(sizeof(fd))] = {0};
  struct iovec iov = {&b, 1};
  struct msghdr m = {.msg_iov = &iov,
                     .msg_iovlen = 1,
                     .msg_control = c,
                     .msg_controllen = sizeof(c)};
  need(recvmsg(sock, &m, MSG_CMSG_CLOEXEC) == 1 && b == 'L' &&
           !(m.msg_flags & (MSG_TRUNC | MSG_CTRUNC)),
       "receive exclusive listener");
  struct cmsghdr *h = CMSG_FIRSTHDR(&m);
  need(h && h->cmsg_type == SCM_RIGHTS && h->cmsg_level == SOL_SOCKET &&
           h->cmsg_len == CMSG_LEN(sizeof(fd)) && !CMSG_NXTHDR(&m, h),
       "listener transport");
  memcpy(&fd, CMSG_DATA(h), sizeof(fd));
  return fd;
}
#define LOAD(x)                                                                \
  BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, x))
#define EQ(x) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, x, 0, 1)
#define RET(x) BPF_STMT(BPF_RET | BPF_K, x)
static void install(int sock) {
  /* Read and private-create calls are both required by the preserved donor FD
     gates. Ordinary paths, all other syscalls and unrelated processes continue.
   */
  struct sock_filter code[] = {
      LOAD(arch),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
      RET(SECCOMP_RET_KILL_PROCESS),
      LOAD(nr),
      BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, 0x40000000u, 0, 1),
      RET(SECCOMP_RET_KILL_PROCESS),
      EQ(SYS_execve),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_execveat),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_open),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_creat),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_openat),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_openat2),
      RET(SECCOMP_RET_USER_NOTIF),
      EQ(SYS_mmap),
      BPF_STMT(BPF_JMP | BPF_JA, 1),
      RET(SECCOMP_RET_ALLOW),
      LOAD(args[2]),
      BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, PROT_EXEC, 0, 1),
      RET(SECCOMP_RET_USER_NOTIF),
      RET(SECCOMP_RET_ALLOW)};
  struct sock_fprog pr = {sizeof(code) / sizeof(*code), code};
  need(!prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "no new privilege");
  int fd = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                   SECCOMP_FILTER_FLAG_NEW_LISTENER, &pr);
  need(fd >= 0, "kernel listener unavailable");
  send_fd(sock, fd);
  close(sock);
  close(fd);
}
static void respond(uint64_t id, int error) {
  struct seccomp_notif_resp r = {
      .id = id,
      .error = -error,
      .flags = error ? 0 : SECCOMP_USER_NOTIF_FLAG_CONTINUE};
  need(!ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &r),
       "invalidated system call");
  if (error)
    denied++;
  else
    continued++;
}
static void readpath(pid_t p, uint64_t address, char path[PATH_MAX]) {
  struct iovec here = {path, PATH_MAX},
               there = {(void *)(uintptr_t)address, PATH_MAX};
  ssize_t n = process_vm_readv(p, &here, 1, &there, 1, 0);
  need(n > 0 && memchr(path, 0, n), "unreadable path in registered rustc");
}
static struct process *identify(pid_t tid) {
  char proc[96], path[PATH_MAX], name[80];
  struct stat st;
  fmt(proc, sizeof(proc), "/proc/%d/exe", tid);
  need(!stat(proc, &st), "kernel executable stat");
  int role = 0;
  for (int i = RUSTC; i <= WILD; i++)
    if (st.st_dev == files[i].st.st_dev && st.st_ino == files[i].st.st_ino)
      role = i;
  if (!role)
    return NULL;
  fetchlink(proc, path, sizeof(path));
  need(same(&st, &files[role].st) && !strcmp(path, files[role].path),
       "foreign or replaced physical executable");
  pid_t pid = group_id(tid);
  bool saw_exec = false;
  for (size_t i = 0; i < nattempt; i++)
    if (attempted[i] == pid) {
      saw_exec = true;
      break;
    }
  /* A fork-without-exec Wild child has its parent's executable and argv. It is
     a real helper, but is not a second execution of that ELF. */
  if (!saw_exec)
    return NULL;
  FILE *f;
  for (size_t i = 0; i < nwatch; i++)
    if (watched[i].pid == pid) {
      need(watched[i].role == role, "re-executed registered PID");
      return &watched[i];
    }
  need(nwatch < sizeof(watched) / sizeof(*watched),
       "too many native processes");
  struct process *p = &watched[nwatch++];
  p->pid = pid;
  p->role = role;
  fmt(name, sizeof(name), "%s-%d.image", roles[role], pid);
  f = newlog(name, "wxe");
  fprintf(f, "%ju\t%ju\t%jd\t%s\n", (uintmax_t)st.st_dev, (uintmax_t)st.st_ino,
          (intmax_t)st.st_size, path);
  finishlog(f);
  copy_proc(pid, roles[role], "cmdline");
  if (role == RUSTC) {
    fmt(name, sizeof(name), "rustc-%d.events", pid);
    finishlog(newlog(name, "wxe"));
  }
  return p;
}
static void record(struct process *p, char tag, int idx, int flags, int fd,
                   int error, struct stat *s, const char *path) {
  char file[80];
  fmt(file, sizeof(file), "rustc-%d.events", p->pid);
  FILE *f = newlog(file, "ae");
  fprintf(f, "%c\t%d\t%x\t%d\t%d\t%ju\t%ju\t%jd\t%s\n", tag, idx, flags, fd,
          error, (uintmax_t)s->st_dev, (uintmax_t)s->st_ino,
          (intmax_t)s->st_size, path);
  finishlog(f);
}
static void mapping(const struct seccomp_notif *n, struct process *p) {
  const __u64 *a = n->data.args;
  pid_t tid = n->pid;
  int fd = (int)a[4];
  if (fd < 0 || (a[3] & MAP_ANONYMOUS))
    return;
  char proc[80], path[PATH_MAX], name[80];
  struct stat s;
  fmt(proc, sizeof(proc), "/proc/%d/fd/%d", tid, fd);
  fetchlink(proc, path, sizeof(path));
  need(!stat(proc, &s), "live mmap FD");
  const char *base = strrchr(path, '/');
  if (!(s.st_dev == files[DRIVER].st.st_dev &&
        s.st_ino == files[DRIVER].st.st_ino) &&
      (!base || !strstr(base, "librustc_driver")))
    return;
  need(same(&s, &files[DRIVER].st) && !strcmp(path, files[DRIVER].path) &&
           !p->pending && !p->mapped && (a[3] & MAP_FIXED) && a[0] && a[1] &&
           (a[2] & PROT_EXEC),
       "ambiguous/foreign driver mapping");
  fmt(name, sizeof(name), "rustc-%d.mmap", p->pid);
  FILE *f = newlog(name, "wxe");
  fprintf(f, "%ju\t%ju\t%jd\t%x\t%jx\t%jx\t%jx\t%s\n", (uintmax_t)s.st_dev,
          (uintmax_t)s.st_ino, (intmax_t)s.st_size, fd, (uintmax_t)a[0],
          (uintmax_t)a[1], (uintmax_t)a[5], path);
  finishlog(f);
  p->pending = true;
}
static void same_context(pid_t tid) {
  char proc[80], a[256], b[256];
  struct stat self, child;
  const char *ns[] = {"ns/mnt", "ns/user", "root"};
  for (int i = 0; i < 3; i++) {
    fmt(proc, sizeof(proc), "/proc/%d/%s", tid, ns[i]);
    need(!stat(proc, &child), "tracee namespace");
    fmt(proc, sizeof(proc), "/proc/self/%s", ns[i]);
    need(!stat(proc, &self) && self.st_dev == child.st_dev &&
             self.st_ino == child.st_ino,
         "different path/credential namespace");
  }
  fmt(proc, sizeof(proc), "/proc/%d/status", tid);
  FILE *x = fopen("/proc/self/status", "re"), *y = fopen(proc, "re");
  need(x && y, "credential gate");
  const char *keys[] = {"Umask:", "Uid:", "Gid:", "Groups:", "CapEff:"};
  for (int i = 0; i < 5; i++) {
    rewind(x);
    rewind(y);
    bool got = false;
    while (fgets(a, sizeof(a), x))
      if (!strncmp(a, keys[i], strlen(keys[i]))) {
        got = true;
        break;
      }
    need(got, "missing supervisor credential");
    got = false;
    while (fgets(b, sizeof(b), y))
      if (!strncmp(b, keys[i], strlen(keys[i]))) {
        got = true;
        break;
      }
    need(got && strchr(a, '\n') && !strcmp(a, b),
         "different effective file access or umask");
  }
  need(!fclose(x) && !fclose(y), "credential close");
}
static void notice(const struct seccomp_notif *n) {
  need(n->data.arch == AUDIT_ARCH_X86_64 &&
           !ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &n->id),
       "foreign/stale notification");
  if (n->data.nr == SYS_execve || n->data.nr == SYS_execveat) {
    pid_t pid = group_id(n->pid);
    bool seen = false;
    for (size_t i = 0; i < nattempt; i++)
      if (attempted[i] == pid)
        seen = true;
    if (!seen) {
      need(nattempt < sizeof(attempted) / sizeof(*attempted),
           "too many exec groups");
      attempted[nattempt++] = pid;
    }
    respond(n->id, 0);
    return;
  }
  struct process *p = identify(n->pid);
  if (!p || p->role != RUSTC) {
    respond(n->id, 0);
    return;
  }
  if (p->pending) {
    copy_proc(p->pid, "rustc", "maps");
    p->mapped = true;
    p->pending = false;
  }
  if (n->data.nr == SYS_mmap) {
    mapping(n, p);
    respond(n->id, 0);
    return;
  }
  char path[PATH_MAX];
  bool at = n->data.nr == SYS_openat || n->data.nr == SYS_openat2;
  readpath(n->pid, n->data.args[at ? 1 : 0], path);
  const char *leaf = strrchr(path, '/');
  leaf = leaf ? leaf + 1 : path;
  const char *names[] = {"dep-graph.bin", "query-cache.bin",
                         "ohm-packed-dep-graph.bin",
                         "ohm-packed-query-cache.bin"};
  int k = 0;
  while (k < 4 && strcmp(leaf, names[k]))
    k++;
  if (k == 4) {
    respond(n->id, 0);
    return;
  }
  need(n->data.nr == SYS_openat && path[0] == '/' && !strstr(path, "/../") &&
           !strstr(path, "/./") && !strstr(path, "//"),
       "alternate table path/syscall");
  int flags = (int)n->data.args[2], owner = -1;
  bool create = (flags & (O_CREAT | O_EXCL)) == (O_CREAT | O_EXCL),
       working = (size_t)(leaf - path) > 9 && !memcmp(leaf - 9, "-working/", 9);
  if ((k < 2 && !(working && create)) ||
      (!create && (flags & O_ACCMODE) != O_RDONLY)) {
    respond(n->id, 0);
    return;
  }
  for (int i = 0; i < nall; i++) {
    size_t len = strlen(allroots[i]);
    if (!strncmp(path, allroots[i], len) && !strncmp(path + len, "/s-", 3) &&
        strchr(path + len + 1, '/') == leaf - 1)
      owner = i;
  }
  need(owner >= 0, "extra unregistered table owner");
  int idx = selected[owner];
  const char *relative = path + strlen(allroots[owner]) + 1;
  char tag = (create ? "DUGQ" : "DUgq")[k];
  /* ADDFD|SEND atomically installs the actual open file in the waiting rustc.
     Limit emulation to the four regular tables in authenticated private owner
     directories. All flags, credentials, creation mode and umask are checked.
   */
  const int read_flags = O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOCTTY;
  const int create_flags = O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC;
  need((create && flags == create_flags && n->data.args[3] == 0666) ||
           (!create && flags == read_flags),
       "unregistered table flags/mode");
  same_context(n->pid);
  char again[PATH_MAX];
  readpath(n->pid, n->data.args[1], again);
  need(!strcmp(again, path) &&
           !ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &n->id),
       "changed request");
  struct stat st = {0};
  int fd, remote;
  /* Pin the active session before either forwarding an FD or rejecting a
     create. A present file, symlink, replacement or subordinate mount is not an
     absent candidate in the registered owner's working directory. */
  char session[NAME_MAX + 1], bound[PATH_MAX], current[PATH_MAX];
  size_t len = (size_t)(leaf - 1 - relative);
  need(len > 0 && len < sizeof(session), "invalid session component");
  memcpy(session, relative, len);
  session[len] = 0;
  const unsigned resolution = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS |
                              RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV;
  struct open_how directory = {.flags = O_PATH | O_DIRECTORY | O_CLOEXEC,
                               .resolve = resolution};
  int sessionfd = syscall(SYS_openat2, allfd[owner], session, &directory,
                          sizeof(directory));
  need(sessionfd >= 0, "changed private session");
  fmt(bound, sizeof(bound), "/proc/self/fd/%d", sessionfd);
  fetchlink(bound, current, sizeof(current));
  fmt(bound, sizeof(bound), "%s/%s", allroots[owner], session);
  struct stat held, named;
  need(!strcmp(bound, current) && !fstat(sessionfd, &held) &&
           !lstat(bound, &named) && S_ISDIR(held.st_mode) &&
           held.st_ino == named.st_ino && held.st_dev == named.st_dev,
       "held and named sessions differ");
  if (tag == 'G' && idx >= 0 && working && deny) {
    need(fstatat(sessionfd, leaf, &st, AT_SYMLINK_NOFOLLOW) < 0 &&
             errno == ENOENT,
         "occupied denied file");
    close(sessionfd);
    memset(&st, 0, sizeof(st));
    respond(n->id, EACCES);
    record(p, 'G', idx, flags, -1, EACCES, &st, path);
    record(p, 'N', idx, flags, -1, EACCES, &st, path);
    return;
  }
  struct open_how how = {.flags = (unsigned)flags,
                         .mode = create ? 0666 : 0,
                         .resolve = resolution};
  fd = syscall(SYS_openat2, sessionfd, leaf, &how, sizeof(how));
  int error = errno;
  close(sessionfd);
  if (fd < 0 && !create && error == ENOENT) {
    /* Let the real optional probe obtain its own kernel result. */
    respond(n->id, 0);
    return;
  }
  need(fd >= 0 && !fstat(fd, &st) && S_ISREG(st.st_mode) &&
           (!create || st.st_size == 0),
       "could not open actual enrolled regular file");
  struct seccomp_notif_addfd add = {.id = n->id,
                                    .flags = SECCOMP_ADDFD_FLAG_SEND,
                                    .srcfd = (unsigned)fd,
                                    .newfd_flags = O_CLOEXEC};
  remote = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &add);
  need(remote >= 0, "kernel did not install actual file descriptor");
  injected++;
  record(p, tag, idx, flags, remote, 0, &st, path);
  close(fd);
}
int main(int argc, char **argv) {
  need(argc >= 6 && !strcmp(argv[4], "--"),
       "usage: notify CONTROL SDK NEW-STATUS -- COMMAND ...");
  table_init(argv[1], argv[2]);
  owners();
  need(!prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0), "subreaper");
  int sock[2];
  need(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sock),
       "listener transport socket");
  pid_t pid = fork();
  need(pid >= 0, "fork");
  if (!pid) {
    close(sock[0]);
    need(!setpgid(0, 0) && !prctl(PR_SET_PDEATHSIG, SIGKILL), "private child");
    install(sock[1]);
    execvp(argv[5], argv + 5);
    _exit(126);
  }
  subject = pid;
  close(sock[1]);
  listener = receive_fd(sock[0]);
  close(sock[0]);
  int pidfd = syscall(SYS_pidfd_open, pid, 0);
  need(pidfd >= 0, "root pidfd");
  struct seccomp_notif_sizes sz;
  need(!syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sz) &&
           sz.seccomp_notif == sizeof(struct seccomp_notif) &&
           sz.seccomp_notif_resp == sizeof(struct seccomp_notif_resp),
       "unsupported kernel notification size");
  struct pollfd f[2] = {{listener, POLLIN, 0}, {pidfd, POLLIN, 0}};
  for (;;) {
    int r = poll(f, 2, -1);
    if (r < 0 && errno == EINTR)
      continue;
    need(r > 0, "poll notification");
    if (f[0].revents & POLLIN) {
      struct seccomp_notif n = {0};
      if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, &n) < 0) {
        need(errno == ENOENT || errno == EINTR, "notification receive");
        continue;
      }
      notice(&n);
    } else if (f[1].revents & POLLIN)
      break;
    else
      need(f[0].revents == POLLHUP, "unexpected listener state");
  }
  int status;
  need(waitpid(pid, &status, 0) == pid && WIFEXITED(status), "root verdict");
  /* Stock Wild forks native helpers. Continue serving their inherited filter,
     and reap every adopted process. Their exit is distinct from Cargo's. */
  FILE *children = newlog("adopted", "wxe");
  for (;;) {
    int extra;
    pid_t adopted = waitpid(-1, &extra, WNOHANG);
    if (adopted > 0) {
      fprintf(children, "%d\t%d\n", adopted, extra);
      need(WIFEXITED(extra) && WEXITSTATUS(extra) == 0,
           "unsuccessful adopted helper");
      continue;
    }
    if (adopted < 0) {
      if (errno == EINTR)
        continue;
      need(errno == ECHILD, "adopted wait");
      break;
    }
    struct pollfd tail = {listener, POLLIN, 0};
    int ready = poll(&tail, 1, 10);
    if (ready < 0 && errno == EINTR)
      continue;
    need(ready >= 0, "post-Cargo poll");
    if (tail.revents & POLLIN) {
      struct seccomp_notif n = {0};
      if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, &n) < 0) {
        need(errno == EINTR || errno == ENOENT, "post-Cargo request");
        continue;
      }
      notice(&n);
    }
  }
  finishlog(children);
  subject = 0;
  for (size_t i = 0; i < nwatch; i++)
    if (watched[i].role == RUSTC)
      need(watched[i].mapped && !watched[i].pending,
           "missing realized driver map");
  table_finish();
  FILE *out = fopen(argv[3], "wxe");
  need(out != NULL, "new status file");
  fprintf(out, "%d\t%zu\t%u\t%u\t%u\n", WEXITSTATUS(status), nwatch, continued,
          injected, denied);
  finishlog(out);
  return WEXITSTATUS(status);
}
