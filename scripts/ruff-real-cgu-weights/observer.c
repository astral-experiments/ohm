/* Read-only Linux x86-64 native-output observer, derived from residual/exec_count.c.
 * observer DIR --owner-exe PHYSICAL_FILE --crate-name NAME -- PROGRAM ARG...
 * Build with cc -O2 -Wall -Wextra -Werror observer.c -lcrypto -o observer
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/perf_event.h>
#include <openssl/evp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

struct count { uint64_t value, enabled, running; };
struct watched {
    unsigned id;
    pid_t group;
    int fd, dirfd, closing, kind;
    uint64_t flags;
    dev_t dev;
    ino_t ino;
    char path[PATH_MAX], base[PATH_MAX], resolved[PATH_MAX];
};
struct task {
    pid_t tid, group;
    int counter, image, owner, in_call, allow_first_exit, unknown_open, exited;
    long nr;
    struct count previous;
    struct watched *operation;
};
enum { OBJECT=1, LLVM_DSO, RUSTC_DRIVER };
static const char *const kinds[]={"","object","llvm","driver"};
static struct task tasks[4096];
static struct watched files[512];
static unsigned next_id, images, owner_images;
static uint64_t hashed_bytes;
static FILE *epochs, *owners, *windows, *digests;
static const char *directory, *crate;
static struct stat selected;

static void need(int ok,const char *why) {
    if(!ok){fprintf(stderr,"native-window refused: %s (errno %d)\n",why,errno);exit(125);}
}
static uint64_t now(void) {
    struct timespec t;need(!clock_gettime(CLOCK_MONOTONIC,&t),"monotonic timestamp");
    return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;
}
static FILE *journal(const char *name) {
    char p[PATH_MAX];int n=snprintf(p,sizeof(p),"%s/%s",directory,name);
    need(n>0&&(size_t)n<sizeof(p),"output path");FILE *f=fopen(p,"wex");need(f!=NULL,"exclusive journal");return f;
}
static void procpath(char *p,size_t size,pid_t tid,int fd,const char *part) {
    int n=fd>=0?snprintf(p,size,"/proc/%d/fd/%d",tid,fd):snprintf(p,size,"/proc/%d/%s",tid,part);
    need(n>0&&(size_t)n<size,"proc path");
}
static int readlink_safe(const char *path,char *out) {
    ssize_t n=readlink(path,out,PATH_MAX);if(n<0){out[0]=0;return 0;}
    need(n>0&&n<PATH_MAX,"untruncated proc link");out[n]=0;return 1;
}
static struct count sample(const struct task *t) {
    struct count c;need(read(t->counter,&c,sizeof(c))==(ssize_t)sizeof(c),"read pinned per-thread instructions");
    need(c.value>=t->previous.value&&c.enabled>=t->previous.enabled&&c.running>=t->previous.running&&c.running<=c.enabled,"monotone raw PMU");
    return c;
}
static void checkpoint(struct task *t) {
    struct count c=sample(t);
    need(fprintf(epochs,"C %d %d %d %"PRIu64" %"PRIu64" %"PRIu64"\n",t->image,t->group,t->tid,
        c.value-t->previous.value,c.enabled-t->previous.enabled,c.running-t->previous.running)>0,"epoch count");t->previous=c;
}
static void resume(const struct task *t,int sig) {
    if(ptrace(t->owner?PTRACE_SYSCALL:PTRACE_CONT,t->tid,0,sig)<0&&errno!=ESRCH)need(0,"resume");
}
static int crate_matches(const char *argv,size_t bytes) {
    unsigned seen=0,match=0;int next=0;
    for(size_t pos=0;pos<bytes;){
        size_t len=strnlen(argv+pos,bytes-pos);need(len<bytes-pos,"NUL-terminated argument");
        const char *arg=argv+pos;pos+=len+1;
        if(next){++seen;match+=!strcmp(arg,crate);next=0;}
        else if(!strcmp(arg,"--crate-name"))next=1;
        else if(!strncmp(arg,"--crate-name=",13)){++seen;match+=!strcmp(arg+13,crate);}
    }
    return !next&&seen==1&&match==1;
}
static void record_image(struct task *t,int exec) {
    char p[96],exe[PATH_MAX],name[32];procpath(p,sizeof(p),t->tid,-1,"exe");
    need(readlink_safe(p,exe),"read executable");struct stat st;need(!stat(p,&st)&&S_ISREG(st.st_mode),"executable identity");
    unsigned id=++images;int n=snprintf(name,sizeof(name),"%05u.nul",id);need(n>0&&(size_t)n<sizeof(name),"argv name");
    FILE *f=journal(name);need(fprintf(f,"%d%c%ju%c%ju%c%s%c",t->group,0,(uintmax_t)st.st_dev,0,(uintmax_t)st.st_ino,0,exe,0)>0,"write image");
    procpath(p,sizeof(p),t->tid,-1,"cmdline");int fd=open(p,O_RDONLY|O_CLOEXEC);need(fd>=0,"argv open");
    size_t cap=16384,used=0;char *args=malloc(cap);need(args!=NULL,"argv allocation");
    for(;;){if(used==cap){need(cap<(8u<<20),"argv bound");cap*=2;args=realloc(args,cap);need(args!=NULL,"argv growth");}
        ssize_t got=read(fd,args+used,cap-used);need(got>=0,"argv read");if(!got)break;used+=(size_t)got;}
    need(used>0&&fwrite(args,1,used,f)==used&&!close(fd)&&!fclose(f),"argv complete");
    int owner=exec&&st.st_dev==selected.st_dev&&st.st_ino==selected.st_ino&&crate_matches(args,used);free(args);
    need(fprintf(epochs,"I %u %d %d %"PRIu64" %s\n",id,t->group,t->tid,now(),exec?"exec":"first")>0,"image epoch");
    if(owner){++owner_images;need(fprintf(owners,"%u\t%d\t%d\t%ju\t%ju\n",id,t->group,t->tid,(uintmax_t)st.st_dev,(uintmax_t)st.st_ino)>0,"selected image");}
    for(size_t i=0;i<sizeof(tasks)/sizeof(*tasks);i++)if(tasks[i].tid&&tasks[i].group==t->group){
        tasks[i].image=(int)id;tasks[i].owner=owner;tasks[i].allow_first_exit=owner;
    }
}
static struct task *lookup(pid_t tid,int create) {
    struct task *slot=NULL;for(size_t i=0;i<sizeof(tasks)/sizeof(*tasks);i++){if(tasks[i].tid==tid)return &tasks[i];if(!tasks[i].tid&&!slot)slot=&tasks[i];}
    if(!create)return NULL;
    need(slot!=NULL,"live task limit");char p[96],line[1024];procpath(p,sizeof(p),tid,-1,"status");FILE *f=fopen(p,"re");need(f!=NULL,"task status");
    pid_t group=0;while(fgets(line,sizeof(line),f))if(sscanf(line,"Tgid: %d",&group)==1)break;
    need(!fclose(f)&&group>0,"Tgid");
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,.pinned=1,.inherit=0,.exclude_kernel=1,.exclude_hv=1,.read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    int fd=(int)syscall(SYS_perf_event_open,&a,tid,-1,-1,PERF_FLAG_FD_CLOEXEC);need(fd>=0,"perf_event_open instructions:u pinned");
    slot->tid=tid;slot->group=group;slot->counter=fd;
    for(size_t i=0;i<sizeof(tasks)/sizeof(*tasks);i++)if(tasks[i].tid&&tasks[i].group==group&&tasks[i].image){
        slot->image=tasks[i].image;slot->owner=tasks[i].owner;slot->allow_first_exit=slot->owner;break;}
    if(!slot->image)record_image(slot,0);
    return slot;
}
static int remote(pid_t tid,uint64_t address,void *buffer,size_t size) {
    struct iovec local={buffer,size},peer={(void *)(uintptr_t)address,size};
    return process_vm_readv(tid,&local,1,&peer,1,0)==(ssize_t)size;
}
static int remote_path(pid_t tid,uint64_t address,char *out) {
    /* Don't require a page after a valid pathname to be readable. */
    long page=sysconf(_SC_PAGESIZE);need(page>0,"page size");
    for(size_t done=0;done<PATH_MAX;){
        uint64_t pos=address+done;if(pos<address)return 0;
        size_t count=(size_t)page-(size_t)(pos%(uint64_t)page);if(count>256)count=256;if(count>PATH_MAX-done)count=PATH_MAX-done;
        if(!remote(tid,pos,out+done,count))return 0;
        if(memchr(out+done,0,count))return 1;
        done+=count;
    }
    return 0;
}
static int classify(const char *path,uint64_t flags) {
    const char *base=strrchr(path,'/');base=base?base+1:path;size_t n=strlen(base);
    if(((flags&O_ACCMODE)==O_WRONLY||(flags&O_ACCMODE)==O_RDWR)&&n>=2&&!strcmp(base+n-2,".o"))return OBJECT;
    if(!strncmp(base,"libLLVM",7)&&strstr(base,".so"))return LLVM_DSO;
    if(!strncmp(base,"librustc_driver",15)&&strstr(base,".so"))return RUSTC_DRIVER;
    return 0;
}
static struct watched *tracked(pid_t group,int fd,int include_closing) {
    if(fd<0)return NULL;
    for(size_t i=0;i<sizeof(files)/sizeof(*files);i++)if(files[i].id&&files[i].group==group&&files[i].fd==fd&&(include_closing||!files[i].closing))return &files[i];
    return NULL;
}
static void hex(FILE *f,const char *s) {
    static const char digits[]="0123456789abcdef";for(;*s;s++){unsigned c=(unsigned char)*s;need(fputc(digits[c>>4],f)!=EOF&&fputc(digits[c&15],f)!=EOF,"hex path");}
}
static void emit(struct task *t,struct watched *w,const char *event,int entering,int64_t ret) {
    struct count c=sample(t);char result[32]="NA";if(!entering)snprintf(result,sizeof(result),"%"PRId64,ret);
    need(fprintf(windows,"%s\t%u\t%d\t%d\t%d\t%"PRIu64"\t%ld\t%s\t%d\t%"PRIu64"\t%d\t%s\t%ju\t%ju\t%"PRIu64"\t%"PRIu64"\t%"PRIu64"\t",
        event,w->id,t->image,t->group,t->tid,now(),t->nr,kinds[w->kind],w->dirfd,w->flags,w->fd,result,(uintmax_t)w->dev,(uintmax_t)w->ino,c.value,c.enabled,c.running)>0,"window header");
    hex(windows,w->path);need(fputc('\t',windows)!=EOF,"path tab");hex(windows,w->base);need(fputc('\t',windows)!=EOF,"base tab");hex(windows,w->resolved);need(fputc('\n',windows)!=EOF,"window row");
}
static void opened(struct task *t,struct watched *w,int fd) {
    need(!tracked(t->group,fd,0),"tracked fd reuse");w->fd=fd;char p[96];procpath(p,sizeof(p),t->tid,fd,NULL);
    int op=open(p,O_PATH|O_CLOEXEC);struct stat st,again;
    need(op>=0&&!fstat(op,&st)&&S_ISREG(st.st_mode)&&readlink_safe(p,w->resolved)&&!stat(p,&again)&&
        st.st_dev==again.st_dev&&st.st_ino==again.st_ino&&!close(op),"stable successful fd identity");
    for(size_t i=0;i<sizeof(files)/sizeof(*files);i++){
        struct watched *other=&files[i];
        if(w->kind==OBJECT&&other!=w&&other->id&&!other->closing&&other->kind==OBJECT)
            need(other->dev!=st.st_dev||other->ino!=st.st_ino,"simultaneous writable object identity");
    }
    w->dev=st.st_dev;w->ino=st.st_ino;need(w->resolved[0]=='/',"absolute opened fd path");
}
static void before_close(struct task *t,struct watched *w) {
    char p[96];procpath(p,sizeof(p),t->tid,w->fd,NULL);int object=w->kind==OBJECT;
    int fd=open(p,(object?O_RDONLY:O_PATH)|O_CLOEXEC);struct stat a,b;
    need(fd>=0&&!fstat(fd,&a)&&S_ISREG(a.st_mode)&&a.st_dev==w->dev&&a.st_ino==w->ino,"independent close fd identity");
    if(object){
        need(a.st_size>=0&&(uint64_t)a.st_size<=(256u<<20)&&hashed_bytes+(uint64_t)a.st_size<=(UINT64_C(4)<<30),"bounded regular object");
        EVP_MD_CTX *ctx=EVP_MD_CTX_new();need(ctx&&EVP_DigestInit_ex(ctx,EVP_sha256(),NULL)==1,"SHA256 init");
        unsigned char data[65536],digest[EVP_MAX_MD_SIZE];off_t pos=0;
        while(pos<a.st_size){off_t remain=a.st_size-pos;size_t want=remain>(off_t)sizeof(data)?sizeof(data):(size_t)remain;
            ssize_t got=pread(fd,data,want,pos);if(got<0&&errno==EINTR)continue;need(got>0&&EVP_DigestUpdate(ctx,data,(size_t)got)==1,"whole object pread");pos+=got;}
        unsigned len=0;need(pread(fd,data,1,pos)==0&&!fstat(fd,&b)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_size==b.st_size&&
            a.st_mtim.tv_sec==b.st_mtim.tv_sec&&a.st_mtim.tv_nsec==b.st_mtim.tv_nsec&&a.st_ctim.tv_sec==b.st_ctim.tv_sec&&a.st_ctim.tv_nsec==b.st_ctim.tv_nsec,"stable whole object");
        need(EVP_DigestFinal_ex(ctx,digest,&len)==1&&len==32,"SHA256 final");EVP_MD_CTX_free(ctx);hashed_bytes+=(uint64_t)pos;
        need(fprintf(digests,"%u\t%jd\t%ju\t%ju\t",w->id,(intmax_t)pos,(uintmax_t)a.st_dev,(uintmax_t)a.st_ino)>0,"digest row");
        for(unsigned i=0;i<len;i++)need(fprintf(digests,"%02x",digest[i])==2,"digest hex");
        need(fputc('\n',digests)!=EOF,"digest newline");
    }
    need(!close(fd),"close observer fd");
}
static int live_object(pid_t group) {
    for(size_t i=0;i<sizeof(files)/sizeof(*files);i++)
        if(files[i].id&&files[i].group==group&&files[i].kind==OBJECT)return 1;
    return 0;
}
static pid_t task_group(pid_t tid) {
    char path[96],line[128];pid_t group=0;procpath(path,sizeof(path),tid,-1,"status");
    FILE *f=fopen(path,"re");need(f!=NULL,"child task status");
    while(fgets(line,sizeof(line),f))if(sscanf(line,"Tgid: %d",&group)==1)break;
    need(!fclose(f)&&group>0,"child task group");return group;
}
static void sysentry(struct task *t,const struct __ptrace_syscall_info *s) {
    need(!t->in_call&&!t->operation,"paired syscall entry");t->in_call=1;t->allow_first_exit=0;t->nr=(long)s->entry.nr;t->unknown_open=0;
    const uint64_t *a=(const uint64_t *)s->entry.args;int dirfd=AT_FDCWD;uint64_t address=0,flags=0;
    switch(t->nr){
    case SYS_close:{struct watched *w=tracked(t->group,(int)a[0],0);if(w){need(!w->closing,"single descriptor close");w->closing=1;t->operation=w;emit(t,w,"close-enter",1,0);before_close(t,w);}return;}
    case SYS_close_range:
        for(size_t i=0;i<sizeof(files)/sizeof(*files);i++)if(files[i].id&&files[i].group==t->group&&files[i].fd>=0&&
            (unsigned)files[i].fd>=a[0]&&(unsigned)files[i].fd<=a[1])need(0,"close_range spans observed fd");
        return;
    case SYS_dup:case SYS_dup2:case SYS_dup3:
        need(!tracked(t->group,(int)a[0],1)&&(t->nr==SYS_dup||!tracked(t->group,(int)a[1],1)),"dup aliases observed fd");return;
    case SYS_fcntl:
        if(a[1]==F_DUPFD||a[1]==F_DUPFD_CLOEXEC)need(!tracked(t->group,(int)a[0],1),"fcntl duplicates observed fd");
        return;
    case SYS_open:address=a[0];flags=(unsigned)a[1];break;
    case SYS_creat:address=a[0];flags=O_WRONLY|O_CREAT|O_TRUNC;break;
    case SYS_openat:dirfd=(int)a[0];address=a[1];flags=(unsigned)a[2];break;
    case SYS_openat2:dirfd=(int)a[0];address=a[1];if(a[3]<sizeof(flags)||!remote(t->tid,a[2],&flags,sizeof(flags))){t->unknown_open=1;return;}break;
    default:return;
    }
    char path[PATH_MAX];if(!remote_path(t->tid,address,path)){t->unknown_open=1;return;}
    int kind=classify(path,flags);if(!kind)return;
    struct watched *w=NULL;for(size_t i=0;i<sizeof(files)/sizeof(*files);i++)if(!files[i].id){w=&files[i];break;}
    need(w&&next_id<100000,"tracked-open budget");w->id=++next_id;w->kind=kind;w->fd=-1;w->dirfd=dirfd;w->group=t->group;w->flags=flags;memcpy(w->path,path,strlen(path)+1);
    if(path[0]!='/'){char p[96];if(dirfd==AT_FDCWD){procpath(p,sizeof(p),t->tid,-1,"cwd");need(readlink_safe(p,w->base),"entry cwd");}
        else if(dirfd>=0){procpath(p,sizeof(p),t->tid,dirfd,NULL);(void)readlink_safe(p,w->base);}}
    t->operation=w;emit(t,w,"open-enter",1,0);
}
static void sysexit(struct task *t,int64_t ret) {
    if(!t->in_call){need(t->allow_first_exit,"unexpected unpaired syscall exit");t->allow_first_exit=0;return;}
    need(!t->unknown_open||ret<0,"unobserved successful open");t->in_call=0;t->unknown_open=0;struct watched *w=t->operation;t->operation=NULL;if(!w)return;
    if(w->closing){emit(t,w,"close-exit",0,ret);need(!ret,"successful matched close");memset(w,0,sizeof(*w));}
    else{if(ret>=0){need(ret<=INT_MAX,"fd range");opened(t,w,(int)ret);}
        emit(t,w,"open-exit",0,ret);if(ret<0)memset(w,0,sizeof(*w));}
}
int main(int argc,char **argv) {
    need(argc>=8&&!strcmp(argv[2],"--owner-exe")&&argv[3][0]=='/'&&!strcmp(argv[4],"--crate-name")&&argv[5][0]&&!strcmp(argv[6],"--"),"DIR --owner-exe ABS --crate-name NAME -- PROGRAM ARGS");
    directory=argv[1];crate=argv[5];need(!stat(argv[3],&selected)&&S_ISREG(selected.st_mode),"selected physical executable");
    epochs=journal("epochs.tsv");owners=journal("owners.tsv");windows=journal("windows.tsv");digests=journal("window-digests.tsv");
    need(fputs("image\ttgid\ttid\tdev\tino\n",owners)>=0&&fputs("event\tid\timage\ttgid\ttid\tmonotonic_ns\tsyscall\tkind\tdirfd\tflags\tfd\tresult\tdev\tino\tvalue\tenabled\trunning\tpath_hex\tbase_hex\tresolved_hex\n",windows)>=0&&fputs("id\tbytes\tdev\tino\tsha256\n",digests)>=0,"headers");
    need(fprintf(epochs,"M %d %"PRIu64"\n",getpid(),now())>0,"observer identity");
    pid_t root=fork();need(root>=0,"fork");if(!root){need(!ptrace(PTRACE_TRACEME,0,0,0),"trace child");raise(SIGSTOP);execvp(argv[7],argv+7);_exit(127);}
    int status,code=-1;need(waitpid(root,&status,0)==root&&WIFSTOPPED(status),"initial stop");
    long opts=PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXIT|PTRACE_O_EXITKILL|PTRACE_O_TRACESYSGOOD;
    need(!ptrace(PTRACE_SETOPTIONS,root,0,opts),"process custody");resume(lookup(root,1),0);
    for(;;){pid_t pid=waitpid(-1,&status,__WALL);if(pid<0){if(errno==EINTR)continue;need(errno==ECHILD,"wait full process tree");break;}
        if(WIFEXITED(status)||WIFSIGNALED(status)){struct task *t=lookup(pid,0);need(t&&t->exited&&!t->operation&&!close(t->counter),"task final epoch");memset(t,0,sizeof(*t));if(pid==root)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);continue;}
        need(WIFSTOPPED(status),"task stop");struct task *t=lookup(pid,1);int event=status>>16,sig=WSTOPSIG(status);
        if(event==PTRACE_EVENT_EXEC){unsigned long former;need(!ptrace(PTRACE_GETEVENTMSG,pid,0,&former)&&(pid_t)former==pid,"stable exec TID");
            need(!t->operation&&(!t->owner||!live_object(t->group)),"no pending object across exec");checkpoint(t);t->in_call=0;record_image(t,1);}
        else if((event==PTRACE_EVENT_FORK||event==PTRACE_EVENT_VFORK||event==PTRACE_EVENT_CLONE)&&t->owner&&live_object(t->group)){
            unsigned long child=0;need(!ptrace(PTRACE_GETEVENTMSG,pid,0,&child)&&child&&
                task_group((pid_t)child)==t->group,"process inherits open owner object");
        }
        else if(event==PTRACE_EVENT_EXIT){need(!t->operation,"no interrupted observed syscall on task exit");checkpoint(t);t->exited=1;}
        else if(!event&&sig==(SIGTRAP|0x80)){need(t->owner,"only selected Tgid uses syscall stops");
            struct __ptrace_syscall_info s={0};long len=ptrace(PTRACE_GET_SYSCALL_INFO,pid,sizeof(s),&s);
            need(len>0&&s.arch==AUDIT_ARCH_X86_64,"native x86-64 syscall stop");if(s.op==PTRACE_SYSCALL_INFO_ENTRY)sysentry(t,&s);else if(s.op==PTRACE_SYSCALL_INFO_EXIT)sysexit(t,s.exit.rval);else need(0,"known syscall stop");}
        resume(t,event||sig==SIGSTOP||sig==(SIGTRAP|0x80)?0:sig);
    }
    for(size_t i=0;i<sizeof(files)/sizeof(*files);i++)need(!files[i].id||files[i].kind!=OBJECT,"complete object windows");
    need(code>=0&&images>=2&&owner_images>0&&!fclose(epochs)&&!fclose(owners)&&!fclose(windows)&&!fclose(digests),"terminal journals and owner");
    return code;
}
