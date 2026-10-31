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
static void resume_process(pid_t pid,int sig) {
    if(ptrace(PTRACE_CONT,pid,0,sig)<0 && errno!=ESRCH)fatal("continue");
}
static void values(FILE *out,const char *name,int fd,int error) {
    uint64_t a[3]={0,0,0};
    if(fd>=0){if(read(fd,a,sizeof(a))!=(ssize_t)sizeof(a))fatal("read counter");close(fd);}
    fprintf(out,"%s\t%d\t%" PRIu64 "\t%" PRIu64 "\t%" PRIu64 "\n",name,error,a[0],a[1],a[2]);
}

static const char *following(const char *buf,size_t size,const char *key) {
    const char *prev=NULL, *value=NULL;
    for(const char *p=buf;p<buf+size;p+=strlen(p)+1) {
        if(prev && !strcmp(prev,key)){need(!value,"duplicate named option");value=p;}
        prev=p;
    }
    return value;
}
static int arg(const char *buf,size_t size,const char *s) {
    for(const char *p=buf;p<buf+size;p+=strlen(p)+1)if(!strcmp(p,s))return 1;
    return 0;
}
static int same(const struct stat *a,const struct stat *b){return a->st_dev==b->st_dev && a->st_ino==b->st_ino;}
static int ends(const char *s,const char *suffix){size_t n=strlen(s),k=strlen(suffix);return n>=k && !strcmp(s+n-k,suffix);}
static void pathcat(char *out,const char *fmt,const char *a,const char *b) {
    int n=snprintf(out,PATH_MAX,fmt,a,b);need(n>0 && n<PATH_MAX,"long path");
}
static const char *names[]={"build_rustc","generator","unicode_rustc","ron"};

int main(int argc,char **argv){
    need(argc>=6,"OUT roster|sham|cal RUSTC|CAL_DIR WILD|DASH PROGRAM ARGS");
    const char *dir=argv[1];int roster=!strcmp(argv[2],"roster"),cal=!strcmp(argv[2],"cal"),sham=!strcmp(argv[2],"sham");
    need(roster||cal||sham,"mode");
    struct stat rust={0},wild={0},calibrators[4];char fn[PATH_MAX],generator[PATH_MAX]={0};
    if(roster){if(stat(argv[3],&rust)||stat(argv[4],&wild))fatal("physical SDK");}
    if(cal)for(int i=0;i<4;i++){pathcat(fn,"%s/%s",argv[3],names[i]);if(stat(fn,&calibrators[i]))fatal("calibrators");}
    pathcat(fn,"%s/%s",dir,"exec.tsv");FILE *exec=fopen(fn,"wx");if(!exec)fatal("exec ledger");
    pathcat(fn,"%s/%s",dir,"spawn.tsv");FILE *spawnlog=fopen(fn,"wx");if(!spawnlog)fatal("spawn ledger");
    pid_t root=fork();if(root<0)fatal("fork");
    if(!root){if(!sham && ptrace(PTRACE_TRACEME,0,0,0)<0)_exit(122);raise(SIGSTOP);execvp(argv[5],argv+5);_exit(127);}
    int status;need(waitpid(root,&status,WUNTRACED)==root && WIFSTOPPED(status) && WSTOPSIG(status)==SIGSTOP,"initial stop");
    int full=counter(root,1);int fullerr=full<0?errno:0,part[4]={-1,-1,-1,-1},errors[4]={0},hits[4]={0},entrypid[4]={0};
    int code=-1,serial=0,real_link=0,wild_finished=0;pid_t wild_pid=-1;
    if(sham){
        if(kill(root,SIGCONT)<0)fatal("start whole-only");
        pid_t result;do{result=waitpid(root,&status,0);}while(result<0 && errno==EINTR);
        need(result==root && (WIFEXITED(status)||WIFSIGNALED(status)),"sham exit");code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
    }else{
        int flags=PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXEC|PTRACE_O_EXITKILL;
        if(ptrace(PTRACE_SETOPTIONS,root,0,flags)<0)fatal("setoptions");
        resume_process(root,0);
        for(;;){
            pid_t pid=waitpid(-1,&status,__WALL);if(pid<0){if(errno==EINTR)continue;if(errno==ECHILD)break;fatal("waitpid");}
            if(WIFEXITED(status)||WIFSIGNALED(status)){if(pid==wild_pid && WIFEXITED(status) && WEXITSTATUS(status)==0)wild_finished=1;if(pid==root)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);continue;}
            if(!WIFSTOPPED(status))continue;
            unsigned event=(unsigned)status>>16;int sig=WSTOPSIG(status);
            if(event==PTRACE_EVENT_EXEC){
                char proc[80],exe[PATH_MAX];snprintf(proc,sizeof(proc),"/proc/%d/exe",pid);
                ssize_t len=readlink(proc,exe,sizeof(exe)-1);if(len<=0 || len>=(ssize_t)sizeof(exe)-1)fatal("readlink");exe[len]=0;
                struct stat actual;if(stat(proc,&actual))fatal("stat exec");size_t size;char *buf=take_cmdline(pid,&size);int role=-1,link_hit=0;
                if(cal){for(int i=0;i<4;i++)if(same(&calibrators[i],&actual) && arg(buf,size,"selected"))role=i;}
                else if(same(&actual,&rust)){
                    const char *krate=following(buf,size,"--crate-name"),*out=following(buf,size,"--out-dir");
                    if(krate && out && !strcmp(krate,"build_script_build") && arg(buf,size,"crates/ruff_unicode_names2/build.rs") && arg(buf,size,"--emit=dep-info,link")){
                        role=0;need(out[0]=='/',"absolute generator out-dir");pathcat(generator,"%s/%s",out,"build_script_build");
                    }else if(krate && out && !strcmp(krate,"unicode_names2") && arg(buf,size,"crates/ruff_unicode_names2/src/lib.rs") && arg(buf,size,"--emit=dep-info,metadata"))role=2;
                    else if(krate && out && !strcmp(krate,"ron") && arg(buf,size,"--emit=dep-info,metadata")){
                        for(const char *p=buf;p<buf+size;p+=strlen(p)+1)if(ends(p,"/ron-0.12.0/src/lib.rs"))role=3;
                    }
                }else if(same(&actual,&wild) && generator[0]){
                    const char *o=following(buf,size,"-o");if(o && !strcmp(o,generator)){link_hit=1;real_link++;wild_pid=pid;}
                }else if(generator[0] && !strcmp(exe,generator)){
                    struct stat output;need(!stat(generator,&output) && same(&actual,&output),"generator current output differs");
                    need(real_link==1 && wild_finished && size==strlen(buf)+1 && !strcmp(buf,generator),"generator before qualified Wild output or has unexpected argv");role=1;
                }
                if(role>=0){need(++hits[role]==1,"duplicate selected image");entrypid[role]=pid;part[role]=counter(pid,0);errors[role]=part[role]<0?errno:0;
                    if(part[role]>=0 && ioctl(part[role],PERF_EVENT_IOC_ENABLE,0)<0)fatal("enable at exec stop");}
                serial++;int n=snprintf(fn,sizeof(fn),"%s/args-%04d",dir,serial);need(n>0 && n<(int)sizeof(fn),"argv name");FILE *f=fopen(fn,"wx");if(!f)fatal("argv record");
                if(fwrite(buf,1,size,f)!=size || fclose(f))fatal("write argv");
                fprintf(exec,"%d\t%d\t%ju\t%ju\t%d\t%d\t%s\n",serial,pid,(uintmax_t)actual.st_dev,(uintmax_t)actual.st_ino,role,link_hit,exe);free(buf);
            }else if(event==PTRACE_EVENT_CLONE||event==PTRACE_EVENT_FORK||event==PTRACE_EVENT_VFORK){
                unsigned long child;if(ptrace(PTRACE_GETEVENTMSG,pid,0,&child)<0)fatal("spawn id");fprintf(spawnlog,"%u\t%d\t%lu\n",event,pid,child);
            }
            resume_process(pid,event || sig==SIGSTOP ? 0 : sig);
        }
    }
    need(code>=0,"no root exit");if(fclose(exec)||fclose(spawnlog))fatal("close logs");pathcat(fn,"%s/%s",dir,"counts.tsv");FILE *f=fopen(fn,"wx");if(!f)fatal("counts file");
    fprintf(f,"root\t%d\t%d\n",root,code);values(f,"whole",full,fullerr);
    for(int i=0;i<4;i++){fprintf(f,"hit-%s\t%d\t%d\n",names[i],hits[i],entrypid[i]);values(f,names[i],part[i],errors[i]);}
    if(fclose(f))fatal("close counts");
    return code;
}
