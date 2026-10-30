#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void fatal(const char *what) { perror(what); exit(125); }
static void need(int valid,const char *why) { if(!valid){ fprintf(stderr,"reject: %s\n",why); exit(124); } }
static int counter(pid_t pid,int on_exec) {
    struct perf_event_attr attr={
        .type=PERF_TYPE_HARDWARE,.size=sizeof(attr),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .inherit=1,.disabled=1,.enable_on_exec=on_exec,.exclude_kernel=1,.exclude_hv=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING
    };
    return syscall(SYS_perf_event_open,&attr,pid,-1,-1,PERF_FLAG_FD_CLOEXEC);
}
static char *take_cmdline(pid_t p,size_t *size) {
    char name[90];snprintf(name,sizeof(name),"/proc/%d/cmdline",p);
    int fd=open(name,O_RDONLY|O_CLOEXEC);if(fd<0)fatal("open cmdline");
    size_t used=0,cap=8192;char *b=malloc(cap);
    if(!b)fatal("malloc");
    for(;;) {
        if(used==cap){need(cap<4194304,"too much argv");cap*=2;b=realloc(b,cap);if(!b)fatal("realloc");}
        ssize_t n=read(fd,b+used,cap-used);
        if(n==-1 && errno==EINTR)continue;
        if(n<0)fatal("read cmdline");
        if(!n)break;
        used+=(size_t)n;
    }
    close(fd);need(used && b[used-1]==0,"truncated exec argv");*size=used;return b;
}
static int target_ron(const char *b,size_t n) {
    int found=0,out=0;const char *prev="";
    for(const char *it=b;it<b+n;it+=strlen(it)+1) {
        if(!strcmp(prev,"--crate-name") && !strcmp(it,"ron"))found++;
        if(!strcmp(prev,"--out-dir"))out++;
        if(!strncmp(it,"--print",7))return 0;
        prev=it;
    }
    return found==1 && out==1;
}
static void resume_process(pid_t pid,int sig) {
    if(ptrace(PTRACE_CONT,pid,0,sig)<0 && errno!=ESRCH)fatal("continue");
}
static void values(FILE *out,const char *name,int fd,int error) {
    uint64_t a[3]={0,0,0};
    if(fd>=0){if(read(fd,a,sizeof(a))!=(ssize_t)sizeof(a))fatal("read counter");close(fd);}
    fprintf(out,"%s\t%d\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",name,error,a[0],a[1],a[2]);
}
int main(int argc,char **argv) {
    need(argc>=5,"observer DIR exact-selected-exe cal|ron PROGRAM [args]");
    const char *dir=argv[1];int cal=!strcmp(argv[3],"cal");need(cal || !strcmp(argv[3],"ron"),"mode");
    struct stat subject;if(stat(argv[2],&subject))fatal("selected physical executable");
    char filename[PATH_MAX];snprintf(filename,sizeof(filename),"%s/exec.tsv",dir);
    FILE *log=fopen(filename,"wx");if(!log)fatal("exec ledger");
    snprintf(filename,sizeof(filename),"%s/events.tsv",dir);FILE *events=fopen(filename,"wx");if(!events)fatal("events");
    pid_t root=fork();if(root<0)fatal("fork");
    if(!root){if(ptrace(PTRACE_TRACEME,0,0,0)<0)_exit(122);raise(SIGSTOP);execvp(argv[4],argv+4);_exit(127);}
    int status;need(waitpid(root,&status,0)==root && WIFSTOPPED(status) && WSTOPSIG(status)==SIGSTOP,"initial trace stop");
    int flags=PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXEC|PTRACE_O_EXITKILL;
    if(ptrace(PTRACE_SETOPTIONS,root,0,flags)<0)fatal("setoptions");
    int full=counter(root,1);int fullerr=full<0 ? errno : 0;
    int part=-1,parterr=0,hits=0,copied=0,code=-1;
    resume_process(root,0);
    for(;;) {
        pid_t pid=waitpid(-1,&status,__WALL);
        if(pid<0){if(errno==EINTR)continue;if(errno==ECHILD)break;fatal("wait");}
        if(WIFEXITED(status)||WIFSIGNALED(status)){
            if(pid==root)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
            continue;
        }
        if(!WIFSTOPPED(status))continue;
        unsigned event=(unsigned)status>>16;int sig=WSTOPSIG(status);
        if(event==PTRACE_EVENT_EXEC){
            char proc[100],exe[PATH_MAX];snprintf(proc,sizeof(proc),"/proc/%d/exe",pid);
            ssize_t len=readlink(proc,exe,sizeof(exe)-1);if(len<=0 || (size_t)len>=sizeof(exe)-1)fatal("read real exe");exe[len]=0;
            struct stat actual;if(stat(proc,&actual))fatal("exec identity");
            size_t size=0;char *args=take_cmdline(pid,&size);
            int matches=actual.st_dev==subject.st_dev && actual.st_ino==subject.st_ino && (cal||target_ron(args,size));
            if(matches){need(++hits==1,"multiple physical Ron processes");part=counter(pid,0);parterr=part<0?errno:0;
                if(part>=0 && ioctl(part,PERF_EVENT_IOC_ENABLE,0)<0)fatal("enable selected at exec stop");}
            copied++;snprintf(filename,sizeof(filename),"%s/args-%04d",dir,copied);FILE *a=fopen(filename,"wx");if(!a)fatal("argv file");
            if(fwrite(args,1,size,a)!=size || fclose(a))fatal("write argv");
            fprintf(log,"%d\t%d\t%ju\t%ju\t%d\t%s\n",copied,pid,(uintmax_t)actual.st_dev,(uintmax_t)actual.st_ino,matches,exe);free(args);
        } else if(event==PTRACE_EVENT_CLONE||event==PTRACE_EVENT_FORK||event==PTRACE_EVENT_VFORK){
            unsigned long child=0;if(ptrace(PTRACE_GETEVENTMSG,pid,0,&child)<0)fatal("spawn id");
            fprintf(events,"%u\t%d\t%lu\n",event,pid,child);
        }
        // Synthetic attach stops must pass without a duplicated signal. Other
        // real signals are delivered to the program, including SIGCHLD/SIGPIPE.
        resume_process(pid,event || sig==SIGSTOP ? 0 : sig);
    }
    if(fclose(log)||fclose(events))fatal("close trace");
    need(code>=0,"missing complete foreground exit");snprintf(filename,sizeof(filename),"%s/counts.tsv",dir);
    FILE *out=fopen(filename,"wx");if(!out)fatal("counts");
    fprintf(out,"root\t%d\t%d\nhits\t%d\n",root,code,hits);
    values(out,"whole",full,fullerr);values(out,"selected",part,parterr);if(fclose(out))fatal("finish counts");return code;
}
