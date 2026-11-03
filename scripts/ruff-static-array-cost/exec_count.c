/* Count each stopped Linux task separately. No tracee memory, argv or environment is modified. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

struct count { uint64_t value, enabled, running; };
struct task { pid_t tid, group; int counter, image; struct count previous; };
static struct task tasks[4096];
static int images;
static FILE *journal;
static const char *directory;
/* Under --lifetime IMAGE, independently count an exec from its first instruction to
   final task exit. Thread inheritance excludes separately spawned processes. */
static int use_lifetime;
static struct stat selected, second;
static int have_second;
static struct lifetime { pid_t pid; int fd, image; } lifetime[64];

static void require(int value, const char *why) { if (!value) { perror(why); exit(125); } }
static uint64_t now(void) { struct timespec t; require(clock_gettime(CLOCK_MONOTONIC,&t)==0,"clock"); return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec; }
static void resume(pid_t pid,int sig) { if(ptrace(PTRACE_CONT,pid,0,sig)<0 && errno!=ESRCH) require(0,"resume"); }
static void output(char *buf, size_t size,const char *format,int id) { int n=snprintf(buf,size,format,id); require(n>0 && (size_t)n<size,"path"); }
static void lifetime_open(pid_t pid, int image, const struct stat *st) {
    if (!use_lifetime) return;
    struct lifetime *slot=NULL;
    for(size_t i=0;i<sizeof(lifetime)/sizeof(lifetime[0]);i++) {
        require(lifetime[i].pid!=pid,"selected program executed another image");
        if(!slot && !lifetime[i].pid)slot=&lifetime[i];
    }
    if((st->st_dev!=selected.st_dev || st->st_ino!=selected.st_ino) &&
       (!have_second || st->st_dev!=second.st_dev || st->st_ino!=second.st_ino))return;
    require(slot!=NULL,"lifetime counter capacity");
    struct perf_event_attr a={
        .type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .inherit=1,.inherit_thread=1,.exclude_kernel=1,.exclude_hv=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    int fd=(int)syscall(__NR_perf_event_open,&a,pid,-1,-1,PERF_FLAG_FD_CLOEXEC);
    require(fd>=0,"selected instruction counter");*slot=(struct lifetime){pid,fd,image};
}
static void lifetime_close(pid_t pid,int status) {
    if(!use_lifetime)return;
    for(size_t i=0;i<sizeof(lifetime)/sizeof(lifetime[0]);i++)if(lifetime[i].pid==pid){
        struct lifetime *p=&lifetime[i];struct count c;
        require(read(p->fd,&c,sizeof(c))==sizeof(c) && close(p->fd)==0,"read completed selected process");
        int code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
        require(fprintf(journal,"R %d %d %"PRIu64" %"PRIu64" %"PRIu64" %d\n",p->image,pid,c.value,c.enabled,c.running,code)>0,"write process lifetime");
        memset(p,0,sizeof(*p));break;
    }
}
static void record_image(struct task *task, const char *trigger) {
    char path[128], executable[4096], name[4096], buffer[16384];
    output(path,sizeof(path),"/proc/%d/exe",task->tid); ssize_t n=readlink(path,executable,sizeof(executable)-1); require(n>0 && (size_t)n<sizeof(executable)-1,"read image"); executable[n]=0;
    struct stat st; require(stat(path,&st)==0,"image identity");
    int id=++images; int used=snprintf(name,sizeof(name),"%s/%05d.nul",directory,id); require(used>0 && (size_t)used<sizeof(name),"output name");
    FILE *f=fopen(name,"wx"); require(f!=NULL,"record open"); require(fprintf(f,"%d%c%ju%c%ju%c%s%c",task->group,0,(uintmax_t)st.st_dev,0,(uintmax_t)st.st_ino,0,executable,0)>0,"image identity write");
    output(path,sizeof(path),"/proc/%d/cmdline",task->tid); int fd=open(path,O_RDONLY|O_CLOEXEC); require(fd>=0,"argv open"); size_t total=0;
    while ((n=read(fd,buffer,sizeof(buffer)))>0) { total+=(size_t)n; require(total<=8u<<20 && fwrite(buffer,1,(size_t)n,f)==(size_t)n,"argv bound"); }
    require(n==0 && total && close(fd)==0 && fclose(f)==0,"argv completed");
    require(fprintf(journal,"I %d %d %d %"PRIu64" %s\n",id,task->group,task->tid,now(),trigger)>0,"image journal");
    if(!strcmp(trigger,"exec"))lifetime_open(task->group,id,&st);
    for(size_t i=0;i<sizeof(tasks)/sizeof(tasks[0]);i++) if(tasks[i].tid && tasks[i].group==task->group) tasks[i].image=id;
}
static void checkpoint(struct task *t) {
    struct count c; require(read(t->counter,&c,sizeof(c))==(ssize_t)sizeof(c),"read counter");
    require(c.value>=t->previous.value && c.enabled>=t->previous.enabled && c.running>=t->previous.running,"counter monotonic");
    require(fprintf(journal,"C %d %d %d %"PRIu64" %"PRIu64" %"PRIu64"\n",t->image,t->group,t->tid,c.value-t->previous.value,c.enabled-t->previous.enabled,c.running-t->previous.running)>0,"count journal");t->previous=c;
}
static struct task *lookup(pid_t tid,int create) {
    struct task *free_slot=NULL;
    for(size_t i=0;i<sizeof(tasks)/sizeof(tasks[0]);i++) { if(tasks[i].tid==tid)return &tasks[i]; if(!tasks[i].tid && !free_slot) free_slot=&tasks[i]; }
    if(!create)return NULL;
    require(free_slot!=NULL,"task bound"); char path[128],line[256]; output(path,sizeof(path),"/proc/%d/status",tid);
    FILE *f=fopen(path,"r"); require(f!=NULL,"task identity");int group=0;
    while(fgets(line,sizeof(line),f)) if(sscanf(line,"Tgid: %d",&group)==1)break;
    require(fclose(f)==0 && group>0,"thread group");
    struct perf_event_attr attr={.type=PERF_TYPE_HARDWARE,.size=sizeof(struct perf_event_attr),.config=PERF_COUNT_HW_INSTRUCTIONS,.exclude_kernel=1,.exclude_hv=1,.read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    int fd=(int)syscall(__NR_perf_event_open,&attr,tid,-1,-1,PERF_FLAG_FD_CLOEXEC);require(fd>=0,"per-thread retired user instructions");
    free_slot->tid=tid;free_slot->group=group;free_slot->counter=fd;
    for(size_t i=0;i<sizeof(tasks)/sizeof(tasks[0]);i++) if(tasks[i].tid && tasks[i].group==group && tasks[i].image) { free_slot->image=tasks[i].image;break; }
    if(!free_slot->image)record_image(free_slot,"first");
    return free_slot;
}
int main(int argc,char **argv) {
    if(argc>=3 && !strcmp(argv[1],"--lifetime")) {
        require(stat(argv[2],&selected)==0 && S_ISREG(selected.st_mode),"selected native image");
        use_lifetime=1;argc-=2;argv+=2;
    }
    if(use_lifetime && argc>=3 && !strcmp(argv[1],"--also")) {
        require(stat(argv[2],&second)==0 && S_ISREG(second.st_mode),"second native image");
        have_second=1;argc-=2;argv+=2;
    }
    require(argc>=4,"OUTPUT_DIR PROGRAM ARGS");directory=argv[1];char out[4096];int n=snprintf(out,sizeof(out),"%s/epochs.tsv",directory);require(n>0 && (size_t)n<sizeof(out),"journal name");journal=fopen(out,"wx");require(journal!=NULL,"open journal");
    require(fprintf(journal,"M %d %"PRIu64"\n",getpid(),now())>0,"monitor journal");
    pid_t root=fork();require(root>=0,"fork");if(!root){require(ptrace(PTRACE_TRACEME,0,0,0)==0,"trace child");raise(SIGSTOP);execvp(argv[2],argv+2);_exit(127);}
    int status,code=-1;require(waitpid(root,&status,0)==root && WIFSTOPPED(status),"initial stop");
    /* Both independent counters observe the very same stopped command. This one
       inherits all descendants and turns on only when the root execs Cargo. */
    struct perf_event_attr outer = {
        .type=PERF_TYPE_HARDWARE,.size=sizeof(outer),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .disabled=1,.inherit=1,.enable_on_exec=1,.exclude_kernel=1,.exclude_hv=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING,
    };
    int inherited=(int)syscall(__NR_perf_event_open,&outer,root,-1,-1,PERF_FLAG_FD_CLOEXEC);
    require(inherited>=0,"whole command counter");
    require(ptrace(PTRACE_SETOPTIONS,root,0,PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXIT|PTRACE_O_EXITKILL)==0,"observer options");lookup(root,1);resume(root,0);
    for(;;){pid_t pid=waitpid(-1,&status,__WALL);if(pid<0){if(errno==EINTR)continue;require(errno==ECHILD,"process tree");break;}
        if(WIFEXITED(status)||WIFSIGNALED(status)){lifetime_close(pid,status);struct task *t=lookup(pid,0);require(t!=NULL,"final task");require(close(t->counter)==0,"counter close");memset(t,0,sizeof(*t));if(pid==root)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);continue;}
        require(WIFSTOPPED(status),"task stop");struct task *t=lookup(pid,1);int event=status>>16,sig=WSTOPSIG(status);
        if(event==PTRACE_EVENT_EXEC){checkpoint(t);record_image(t,"exec");}
        if(event==PTRACE_EVENT_EXIT)checkpoint(t);
        resume(pid,event||sig==SIGSTOP||sig==SIGTRAP?0:sig);
    }
    struct count all;
    require(read(inherited,&all,sizeof(all))==sizeof(all) && close(inherited)==0,"read whole command");
    require(fprintf(journal,"W %"PRIu64" %"PRIu64" %"PRIu64" %d\n",all.value,all.enabled,all.running,code)>0,"whole command journal");
    require(code>=0 && images>=2 && fclose(journal)==0,"capture complete");return code;
}
