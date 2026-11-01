/* GNU x86-64 diagnostic. Both lanes use this same ELF and an identical environment. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#define NOWNERS 32
static char owners[NOWNERS][PATH_MAX], control[PATH_MAX];
static int nowners, events = -1;
static bool rustc_role, block;
static int (*real_open64)(const char *, int, ...);

static void die(void) { static const char msg[] = "pack-gate observer refused\n"; syscall(SYS_write, 2, msg, sizeof(msg)-1); _exit(115); }
static bool same(const struct stat *a, const char *b) {
    struct stat z;
    return b && stat(b, &z)==0 && a->st_dev==z.st_dev && a->st_ino==z.st_ino;
}
static int rawopen(const char *p, int flags, mode_t mode) {
    return (int)syscall(SYS_openat, AT_FDCWD, p, flags|O_CLOEXEC|O_NOFOLLOW, mode);
}
static void save_proc(const char *role, const char *name) {
    char dest[PATH_MAX], path[96], buf[8192];
    if (snprintf(dest,sizeof(dest),"%s/%s-%ld.%s",control,role,(long)getpid(),name)>=(int)sizeof(dest)) die();
    snprintf(path,sizeof(path),"/proc/self/%s",name);
    int in=(int)syscall(SYS_openat,AT_FDCWD,path,O_RDONLY|O_CLOEXEC,0), out=rawopen(dest,O_WRONLY|O_CREAT|O_EXCL,0600);
    if (in<0 || out<0) die();
    ssize_t n;
    while ((n=read(in,buf,sizeof(buf)))>0) if (write(out,buf,(size_t)n)!=n) die();
    if (n<0 || close(in) || close(out)) die();
}
__attribute__((constructor)) static void start(void) {
    real_open64=dlsym(RTLD_NEXT,"open64");
    if (!real_open64) die();
    const char *dir=getenv("OHM_QA_PACK_CONTROL");
    if (!dir) return;
    struct stat me;
    if (stat("/proc/self/exe",&me)) die();
    const char *role=same(&me,getenv("OHM_QA_PACK_RUSTC"))?"rustc":
                     same(&me,getenv("OHM_QA_PACK_WILD"))?"wild":
                     same(&me,getenv("OHM_QA_PACK_CARGO"))?"cargo":NULL;
    if (!role) return;
    if (dir[0]!='/' || strlen(dir)>=sizeof(control)) die();
    strcpy(control,dir);
    char image_file[PATH_MAX], image_name[PATH_MAX], image_record[PATH_MAX+128];
    if (snprintf(image_file,sizeof(image_file),"%s/%s-%ld.image",control,role,(long)getpid())>=(int)sizeof(image_file)) die();
    ssize_t end=readlink("/proc/self/exe",image_name,sizeof(image_name)-1);
    if (end<=0 || end>=(ssize_t)sizeof(image_name)-1) die();
    image_name[end]=0;
    int im=rawopen(image_file,O_WRONLY|O_CREAT|O_EXCL,0600);
    int len=snprintf(image_record,sizeof(image_record),"%llu\t%llu\t%lld\t%s\n",(unsigned long long)me.st_dev,
                     (unsigned long long)me.st_ino,(long long)me.st_size,image_name);
    if (im<0 || len<=0 || len>=(int)sizeof(image_record) || write(im,image_record,(size_t)len)!=len || close(im)) die();
    save_proc(role,"cmdline");
    if (strcmp(role,"rustc")) return;
    save_proc(role,"maps");
    char file[PATH_MAX], input[NOWNERS*PATH_MAX+16];
    if (snprintf(file,sizeof(file),"%s/config",control)>=(int)sizeof(file)) die();
    int fd=rawopen(file,O_RDONLY,0); struct stat cfg;
    if (fd<0 || fstat(fd,&cfg) || !S_ISREG(cfg.st_mode) || cfg.st_size<3 || cfg.st_size>=(off_t)sizeof(input)) die();
    if (read(fd,input,(size_t)cfg.st_size)!=cfg.st_size || close(fd)) die();
    input[cfg.st_size]=0;
    if (input[1]!='\n'||(input[0]!='B'&&input[0]!='P')||input[cfg.st_size-1]!='\n') die();
    block=input[0]=='B';
    char *next=input+2, *line;
    while ((line=strsep(&next,"\n")) && *line) {
        if (nowners>=NOWNERS || line[0]!='/' || strlen(line)>=PATH_MAX || strchr(line,'\t')) die();
        strcpy(owners[nowners++],line);
    }
    if (next || !nowners) die();
    if (snprintf(file,sizeof(file),"%s/rustc-%ld.events",control,(long)getpid())>=(int)sizeof(file)) die();
    events=rawopen(file,O_WRONLY|O_CREAT|O_EXCL|O_APPEND,0600);
    if (events<0) die();
    rustc_role=true;
}
static int selected(const char *path, const char *name) {
    for (int i=0;i<nowners;i++) {
        size_t len=strlen(owners[i]);
        if (!strncmp(path,owners[i],len) && !strncmp(path+len,"/s-",3) && strchr(path+len+1,'/')==name-1)
            return i;
    }
    return -1;
}
static void note(char tag,int index,int flags,int fd,int err,const char *path) {
    char line[PATH_MAX+160]; struct stat s={0};
    if (fd>=0 && (fstat(fd,&s)||!S_ISREG(s.st_mode))) die();
    int n=snprintf(line,sizeof(line),"%c\t%d\t%x\t%d\t%d\t%llu\t%llu\t%lld\t%s\n",tag,index,flags,fd,err,
                   (unsigned long long)s.st_dev,(unsigned long long)s.st_ino,(long long)s.st_size,path);
    if (n<=0 || n>=(int)sizeof(line) || syscall(SYS_write,events,line,(size_t)n)!=n) die();
}
int open64(const char *path,int flags,...) {
    mode_t mode=0;
    if ((flags&O_CREAT)||(flags&O_TMPFILE)==O_TMPFILE) {
        va_list ap; va_start(ap,flags);mode=va_arg(ap,mode_t);va_end(ap);
    }
    /* The loader may call us before this DSO's constructor. GNU x86-64 open64 uses openat. */
    if (!real_open64) return (int)syscall(SYS_openat,AT_FDCWD,path,flags,mode);
    if (!rustc_role) return real_open64(path,flags,mode);
    const char *last=strrchr(path,'/'), *name=last?last+1:path;
    bool graph=!strcmp(name,"ohm-packed-dep-graph.bin"), query=!strcmp(name,"ohm-packed-query-cache.bin");
    bool raw_graph=!strcmp(name,"dep-graph.bin"), raw_query=!strcmp(name,"query-cache.bin");
    if (!graph&&!query&&!raw_graph&&!raw_query) return real_open64(path,flags,mode);
    int index=last?selected(path,name):-1;
    bool create=(flags&(O_EXCL|O_CREAT))==(O_EXCL|O_CREAT);
    bool working=last && (size_t)(last-path)>=8 && !memcmp(last-8,"-working",8);
    /* A fallback allocates a new private directory. Bind both restored streams to
       the very directory that the successful compiler finally publishes. */
    if (raw_graph || raw_query) {
        int fd=real_open64(path,flags,mode), err=errno;
        if (create && working) note(raw_graph?'D':'U',index,flags,fd,fd<0?err:0,path);
        errno=err;
        return fd;
    }
    bool refuse=graph && index>=0 && create && (flags&O_ACCMODE)==O_RDWR && working && block;
    int fd=refuse?-1:real_open64(path,flags,mode);
    int err=refuse?EACCES:errno;
    char tag=create?(graph?'G':'Q'):(graph?'g':'q');
    if (create || (fd>=0 && (flags&O_ACCMODE)==O_RDONLY)) note(tag,index,flags,fd,fd<0?err:0,path);
    /* One evidence write here balances the query-create observation on pass. N records
       a fault decision, not a query syscall. Any actual query create still records Q. */
    if (refuse) note('N',index,flags,-1,EACCES,path);
    errno=err;
    return fd;
}
