#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* Only the positive enrolled futimens call can be changed. Keep normal libc
   behavior for every other fd, process, source epoch, and timestamp operation. */
typedef int (*utime_fn)(int, const struct timespec[2]);

static int same_bytes(int a, int b, off_t size) {
    if (size <= 0 || size > 64 * 1024 * 1024) return 0;
    unsigned char x[32768], y[sizeof(x)];
    for (off_t off = 0; off < size;) {
        size_t n = (size_t)(size - off);
        if (n > sizeof(x)) n = sizeof(x);
        if (pread(a, x, n, off) != (ssize_t)n ||
            pread(b, y, n, off) != (ssize_t)n || memcmp(x, y, n)) return 0;
        off += (off_t)n;
    }
    return 1;
}
static int stable(const struct stat *a, const struct stat *b) {
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
        a->st_ctim.tv_sec==b->st_ctim.tv_sec && a->st_ctim.tv_nsec==b->st_ctim.tv_nsec &&
        a->st_mtim.tv_sec==b->st_mtim.tv_sec && a->st_mtim.tv_nsec==b->st_mtim.tv_nsec;
}
static int paired(const char *path) {
    struct stat self, enrolled;
    return path && !stat("/proc/self/exe",&self) && !stat(path,&enrolled) &&
        self.st_dev==enrolled.st_dev && self.st_ino==enrolled.st_ino;
}
int futimens(int fd, const struct timespec req[2]) {
    int entry_errno=errno;
    utime_fn real=(utime_fn)dlsym(RTLD_NEXT,"futimens");
    if (!real) _exit(123);
    const char *cfg=getenv("QA_INSTA_CONFIG"), *actor=getenv("QA_INSTA_ACTOR");
    struct stat before;
    char mode[8], ref[PATH_MAX], log[PATH_MAX];
    uintmax_t dev, ino;
    int enrolled=0;
    if (paired(actor) && cfg && !fstat(fd,&before) && S_ISREG(before.st_mode)) {
        FILE *f=fopen(cfg,"re");
        if (f) {
            if (fscanf(f,"%7s %ju %ju %4095s %4095s",mode,&dev,&ino,ref,log)!=5) _exit(124);
            fclose(f);
            enrolled=dev==(uintmax_t)before.st_dev && ino==(uintmax_t)before.st_ino;
        }
    }
    if (!enrolled) {errno=entry_errno;return real(fd,req);}
    char fdpath[100], path[PATH_MAX];
    snprintf(fdpath,sizeof(fdpath),"/proc/self/fd/%d",fd);
    ssize_t length=readlink(fdpath,path,sizeof(path)-1);
    if (length<1 || (size_t)length>=sizeof(path)-1) _exit(125);
    path[length]=0;
    int a=open(fdpath,O_RDONLY|O_CLOEXEC|O_NOATIME);
    int b=open(ref,O_RDONLY|O_CLOEXEC|O_NOATIME|O_NOFOLLOW);
    struct stat copy, acquired, checked, checked_copy;
    int eq=a>=0 && b>=0 && !fstat(a,&acquired) && stable(&before,&acquired) &&
        !fstat(b,&copy) && S_ISREG(copy.st_mode) && !(copy.st_mode & 0222) &&
        copy.st_size==before.st_size && same_bytes(a,b,before.st_size) &&
        !fstat(a,&checked) && stable(&checked,&before) &&
        !fstat(b,&checked_copy) && stable(&copy,&checked_copy);
    if (a>=0) close(a);
    if (b>=0) close(b);
    if ((strcmp(mode,"allow") && strcmp(mode,"hold")) || !req) _exit(126);
    int eligible=req[0].tv_nsec==UTIME_OMIT && req[1].tv_nsec>=0 && req[1].tv_nsec<1000000000L;
    int held=eq && eligible && !strcmp(mode,"hold");
    struct timespec actual[2]={req[0],req[1]};
    if (held) {actual[1].tv_sec=0;actual[1].tv_nsec=UTIME_OMIT;}
    errno=entry_errno;
    int result=real(fd,actual), err=errno;
    struct stat after;
    if (fstat(fd,&after)) _exit(127);
    char row[8192];
    int cnt=snprintf(row,sizeof(row),"%d\t%ld\t%d\t%s\t%d\t%d\t%d\t%ju\t%ju\t%jd\t%ld\t%jd\t%ld\t%jd\t%ld\t%jd\t%ld\t%jd\t%ld\t%jd\t%ld\t%d\t%s\n",
        getpid(),syscall(SYS_gettid),fd,mode,eq,eligible,held,dev,ino,
        (intmax_t)before.st_mtim.tv_sec,before.st_mtim.tv_nsec,(intmax_t)after.st_mtim.tv_sec,after.st_mtim.tv_nsec,
        (intmax_t)req[0].tv_sec,req[0].tv_nsec,(intmax_t)req[1].tv_sec,req[1].tv_nsec,
        (intmax_t)after.st_ctim.tv_sec,after.st_ctim.tv_nsec,
        (intmax_t)before.st_ctim.tv_sec,before.st_ctim.tv_nsec,result,path);
    int ledger=open(log,O_WRONLY|O_APPEND|O_CLOEXEC|O_NOFOLLOW);
    if (ledger<0 || cnt<=0 || (size_t)cnt>=sizeof(row) || write(ledger,row,cnt)!=cnt) _exit(128);
    close(ledger);errno=err;return result;
}
