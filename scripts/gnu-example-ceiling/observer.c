#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Same event and exec-entry boundary as the recorded Unicode observer. All role
 * decisions can be reconstructed independently using the image, NUL argv and edges. */
static void fatal(const char *s){perror(s);exit(125);}
static void need(int yes,const char *s){if(!yes){fprintf(stderr,"rejected: %s\n",s);exit(124);}}
static struct perf_event_attr spec(int on_exec){
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .inherit=1,.disabled=1,.enable_on_exec=on_exec,.exclude_kernel=1,.exclude_hv=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    return a;
}
static int event(pid_t pid,int on_exec){
    struct perf_event_attr a=spec(on_exec);
    return syscall(SYS_perf_event_open,&a,pid,-1,-1,PERF_FLAG_FD_CLOEXEC);
}
static FILE *file(const char *root,const char *leaf){
    char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/%s",root,leaf);need(n>0 && (size_t)n<sizeof(path),"path");
    FILE *f=fopen(path,"wx");if(!f)fatal(path);return f;
}
static char *argv_at_exec(pid_t pid,size_t *len){
    char path[80];snprintf(path,sizeof(path),"/proc/%d/cmdline",pid);int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)fatal(path);
    size_t size=4096,used=0;char *buf=malloc(size);if(!buf)fatal("malloc");
    for(;;){if(size==used){need(size<4*1024*1024,"argv size");size*=2;buf=realloc(buf,size);if(!buf)fatal("realloc");}
        ssize_t n=read(fd,buf+used,size-used);if(n<0 && errno==EINTR)continue;if(n<0)fatal("cmdline");if(!n)break;used+=n;}
    if(close(fd))fatal("close argv");
    need(used && buf[used-1]==0,"unclosed argv");*len=used;return buf;
}
static int arg(const char *b,size_t size,const char *s){for(const char *v=b;v<b+size;v+=strlen(v)+1)if(!strcmp(v,s))return 1;return 0;}
static int same(struct stat a,struct stat b){return a.st_dev==b.st_dev && a.st_ino==b.st_ino;}
static void resume(pid_t p,int s){if(ptrace(PTRACE_CONT,p,0,s)<0 && errno!=ESRCH)fatal("PTRACE_CONT");}
struct sample {pid_t pid;int serial,role,fd,error;};
static struct sample counts[100];static int ncounts=0;
static void enroll(pid_t p,int serial,int role,int on_exec,int counters){
    need(ncounts<(int)(sizeof(counts)/sizeof(counts[0])),"too many counts");int fd=-1,err=0;
    if(counters){fd=event(p,on_exec);if(fd<0)err=errno;else if(!on_exec && ioctl(fd,PERF_EVENT_IOC_ENABLE,0))fatal("enable counter");}
    counts[ncounts++]=(struct sample){p,serial,role,fd,err};
}
static void newcomer(FILE *ledger,pid_t pid){
    char path[90],*line=NULL;size_t cap=0;int tgid=0,ppid=-1;snprintf(path,sizeof(path),"/proc/%d/status",pid);
    FILE *f=fopen(path,"r");if(!f)fatal("stopped task status");
    while(getline(&line,&cap,f)>=0){int v;if(sscanf(line,"Tgid:%d",&v)==1)tgid=v;else if(sscanf(line,"PPid:%d",&v)==1)ppid=v;}
    free(line);if(fclose(f))fatal("close status");need(tgid>0 && ppid>=0,"incomplete stopped status");fprintf(ledger,"task\t%d\t%d\t%d\n",pid,tgid,ppid);
}
int main(int argc,char **argv){
    need(argc>=8,"OUT tree|plain|topology RUSTC CC COLLECT2 WILD PROGRAM [ARGS]");
    int plain=!strcmp(argv[2],"plain"),counters=strcmp(argv[2],"topology")!=0;need(plain || !strcmp(argv[2],"tree") || !counters,"mode");
    struct stat phys[4];for(int i=0;i<4;++i){if(stat(argv[3+i],&phys[i]))fatal("physical selectors");for(int k=0;k<i;++k)need(!same(phys[k],phys[i]),"selectors alias");}
    FILE *log=file(argv[1],"tasks.tsv"),*exec=file(argv[1],"exec.tsv"),*v=file(argv[1],"samples.tsv"),*abi=file(argv[1],"abi.tsv");
    fprintf(abi,"%zu\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n",sizeof(struct perf_event_attr),PERF_TYPE_HARDWARE,PERF_COUNT_HW_INSTRUCTIONS,PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING,1,1,1,1,(int)PERF_FLAG_FD_CLOEXEC);
    if(fclose(abi))fatal("write ABI");
    for(int on=0;on<2;++on){
        struct perf_event_attr a=spec(on);FILE *body=file(argv[1],on?"whole-attr.bin":"subtree-attr.bin");
        if(fwrite(&a,1,sizeof(a),body)!=sizeof(a) || fclose(body))fatal("write event attributes");
    }
    /* The plain parent adopts orphaned linker workers. The tracer already waits
     * for every tracee; adopting one there would report its death a second time. */
    if(plain && prctl(PR_SET_CHILD_SUBREAPER,1L))fatal("subreaper");
    pid_t root=fork();if(root<0)fatal("fork root");if(!root){if(!plain && ptrace(PTRACE_TRACEME,0,0,0)<0)_exit(122);raise(SIGSTOP);execvp(argv[7],argv+7);_exit(127);}
    int status,code=-1,serial=0;need(waitpid(root,&status,WUNTRACED)==root && WIFSTOPPED(status) && WSTOPSIG(status)==SIGSTOP,"initial stop");
    fprintf(log,"root\t%d\n",root);enroll(root,0,0,1,counters);
    if(plain){if(kill(root,SIGCONT))fatal("release plain");}
    else{
        int flags=PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXEC|PTRACE_O_EXITKILL;
        if(ptrace(PTRACE_SETOPTIONS,root,0,flags)<0)fatal("set ptrace options");
        newcomer(log,root);resume(root,0);
    }
    for(;;){pid_t p=waitpid(-1,&status,plain?0:__WALL);if(p<0){if(errno==EINTR)continue;if(errno==ECHILD)break;fatal("wait tree");}
        if(WIFEXITED(status)||WIFSIGNALED(status)){int term=WIFSIGNALED(status)?WTERMSIG(status):0,rc=term?128+term:WEXITSTATUS(status);if(p==root)code=rc;
            fprintf(log,"exit\t%d\t%d\t%d\n",p,rc,term);continue;}
        need(!plain && WIFSTOPPED(status),"unexpected wait status");unsigned e=(unsigned)status>>16;int sig=WSTOPSIG(status);
        if(e==PTRACE_EVENT_EXEC){unsigned long old;if(ptrace(PTRACE_GETEVENTMSG,p,0,&old)<0)fatal("exec message");need(old==(unsigned long)p,"thread replaced a process at exec");
            char exe[PATH_MAX],proc[80];snprintf(proc,sizeof(proc),"/proc/%d/exe",p);ssize_t n=readlink(proc,exe,sizeof(exe)-1);if(n<=0 || (size_t)n>=sizeof(exe)-1)fatal("exec path");exe[n]=0;
            struct stat st;if(stat(proc,&st))fatal("exec stat");size_t bytes;char *b=argv_at_exec(p,&bytes);int type=0;
            for(int i=0;i<4;++i)if(same(st,phys[i]))type=i+1;
            /* All full codegen rustcs are counted. The verifier assigns examples and
             * prices the separately edited library only after replaying the actual argv. */
            int selected=(type==1 && arg(b,bytes,"--crate-name") && arg(b,bytes,"--out-dir")) || ((type==2 || type==4) && arg(b,bytes,"-o"));
            ++serial;if(selected)enroll(p,serial,type,0,counters);char name[38];snprintf(name,sizeof(name),"args-%04d",serial);FILE *f=file(argv[1],name);
            if(fwrite(b,1,bytes,f)!=bytes || fclose(f))fatal("save argv");
            free(b);
            fprintf(exec,"%d\t%d\t%d\t%d\t%ju\t%ju\t%s\n",serial,p,type,selected,(uintmax_t)st.st_dev,(uintmax_t)st.st_ino,exe);
            fprintf(log,"exec\t%d\t%d\n",p,serial);
        }else if(e==PTRACE_EVENT_CLONE||e==PTRACE_EVENT_FORK||e==PTRACE_EVENT_VFORK){unsigned long child;if(ptrace(PTRACE_GETEVENTMSG,p,0,&child)<0)fatal("child ID");
            fprintf(log,"spawn\t%d\t%lu\t%u\n",p,child,e);
        }else if(!e && sig==SIGSTOP){newcomer(log,p);}
        else if(e)need(0,"unknown kernel ptrace event");
        resume(p,(e || sig==SIGSTOP)?0:sig);
    }
    need(code>=0,"missing root exit");for(int i=0;i<ncounts;++i){struct sample *s=&counts[i];uint64_t raw[3]={0};long got=-1;
        if(s->fd>=0){got=read(s->fd,raw,sizeof(raw));if(got!=(long)sizeof(raw))fatal("full PMU read");if(close(s->fd))fatal("close PMU");}
        fprintf(v,"%d\t%d\t%d\t%d\t%ld\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",s->serial,s->pid,s->role,s->error,got,raw[0],raw[1],raw[2]);}
    if(fclose(log)||fclose(exec)||fclose(v))fatal("close native receipt");
    return code;
}
