/* Measure one genuine process at its successful exec stop. Linux inherits the event into
 * every subsequent thread and descendant. Keep its fd open until the complete Cargo tree exits. */
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
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

struct task { pid_t tid, group; int image; };
static struct task tasks[4096];
static FILE *journal;
static const char *directory, *mode, *owner;
static struct stat owner_exe;
static int images, selected, event_fd=-1, measured;
static pid_t leader;

static void require(int yes, const char *why) { if (!yes) { perror(why); exit(125); } }
static void output(char *b,size_t sz,const char *fmt,int n) { int r=snprintf(b,sz,fmt,n);require(r>0 && (size_t)r<sz,"path bound"); }
static uint64_t now(void){struct timespec s;require(clock_gettime(CLOCK_MONOTONIC,&s)==0,"clock");return (uint64_t)s.tv_sec*1000000000+s.tv_nsec;}
#include "driver_maps.inc"

static void account(struct task *t) {
    require(event_fd<0,"one selected PMU root");
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .disabled=1,.pinned=1,.inherit=1,.exclude_kernel=1,.exclude_hv=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    event_fd=(int)syscall(__NR_perf_event_open,&a,t->tid,-1,-1,PERF_FLAG_FD_CLOEXEC);
    require(event_fd>=0 && ioctl(event_fd,PERF_EVENT_IOC_RESET,0)==0 && ioctl(event_fd,PERF_EVENT_IOC_ENABLE,0)==0,"enable inherited user instructions");
    measured=t->image;
}

/* Cargo receives an explicit credential-free environment. Preserve that original for the
 * optional exact-operand replay. A credential-bearing environment is never serialized. */
static void owner_environment(pid_t tid,int image) {
    char proc[80],path[4096];output(proc,sizeof(proc),"/proc/%d/environ",tid);
    FILE *input=fopen(proc,"rb");require(input!=NULL,"selected environment");
    size_t limit=2u<<20;char *data=malloc(limit);require(data!=NULL,"bounded environment");
    size_t n=fread(data,1,limit,input);
    require(n>0 && n<limit && !ferror(input) && fclose(input)==0 && data[n-1]==0,"complete selected environment");
    for(char *item=data;item<data+n;item+=strlen(item)+1){
        char *eq=strchr(item,'=');require(eq && eq>item,"environment key");
        *eq=0;require(!strcasestr(item,"TOKEN") && !strcasestr(item,"SECRET") && !strcasestr(item,"PASSWORD") && !strcasestr(item,"CREDENTIAL"),"credential-bearing key");
        *eq='=';
    }
    int used=snprintf(path,sizeof(path),"%s/%05d.env",directory,image);
    require(used>0 && (size_t)used<sizeof(path),"environment path");
    FILE *f=fopen(path,"wx");require(f && fwrite(data,1,n,f)==n && fclose(f)==0,"environment receipt");free(data);
}

static void image_record(struct task *t,const char *why) {
    char proc[80],exe[4096],name[4096],buf[16384];
    output(proc,sizeof(proc),"/proc/%d/exe",t->tid);
    ssize_t n=readlink(proc,exe,sizeof(exe)-1);require(n>0 && (size_t)n<sizeof(exe)-1,"executable");exe[n]=0;
    struct stat st;require(stat(proc,&st)==0,"executable file");
    int id=++images,used=snprintf(name,sizeof(name),"%s/%05d.nul",directory,id);
    require(used>0 && (size_t)used<sizeof(name),"argv path");
    FILE *out=fopen(name,"wx");require(out && fprintf(out,"%d%c%ju%c%ju%c%s%c",t->group,0,(uintmax_t)st.st_dev,0,(uintmax_t)st.st_ino,0,exe,0)>0,"argv header");
    output(proc,sizeof(proc),"/proc/%d/cmdline",t->tid);int fd=open(proc,O_RDONLY|O_CLOEXEC);require(fd>=0,"argv open");
    size_t len=0,size=0;char *args=NULL;
    while((n=read(fd,buf,sizeof(buf)))>0){
        require(len+(size_t)n<8u<<20,"argv bounds");
        if(len+(size_t)n>size){size=2*(len+(size_t)n);args=realloc(args,size);require(args!=NULL,"argv allocation");}
        memcpy(args+len,buf,(size_t)n);len+=(size_t)n;
        require(fwrite(buf,1,(size_t)n,out)==(size_t)n,"argv body");
    }
    require(n==0 && len>0 && args[len-1]==0 && close(fd)==0 && fclose(out)==0,"complete argv");
    require(fprintf(journal,"I %d %d %d %"PRIu64" %s\n",id,t->group,t->tid,now(),why)>0,"image roster");
    for(size_t i=0;i<4096;i++)if(tasks[i].tid && tasks[i].group==t->group)tasks[i].image=id;
    int crate=0,emits=0;const char *previous="";
    for(char *arg=args;arg<args+len;arg+=strlen(arg)+1){if(strcmp(previous,"--crate-name")==0 && strcmp(arg,owner)==0)crate++;
        if(strcmp(arg,"--emit=dep-info,metadata")==0)emits++;
        previous=arg;}
    if(strcmp(why,"exec")==0 && st.st_dev==owner_exe.st_dev && st.st_ino==owner_exe.st_ino && crate==1 && emits==1){
        require(!selected && t->tid==t->group,"one genuine owner exec");selected=id;
        if(strrchr(exe,'/') && strcmp(strrchr(exe,'/'),"/rustc")==0)owner_environment(t->tid,id);
        require(fprintf(journal,"A %d %d\n",id,t->tid)>0,"selected image");
        if(strcmp(mode,"owner")==0)account(t);
    }
    if(!measured && strcmp(mode,"whole")==0 && strcmp(why,"exec")==0 && t->tid==leader)account(t);
    free(args);
}

static struct task *lookup(pid_t tid,int create) {
    struct task *slot=NULL;
    for(size_t i=0;i<4096;i++){if(tasks[i].tid==tid)return &tasks[i];if(!slot && !tasks[i].tid)slot=&tasks[i];}
    if(!create)return NULL;
    require(slot!=NULL,"task bound");char p[80],line[256];output(p,sizeof(p),"/proc/%d/status",tid);
    FILE *f=fopen(p,"r");require(f!=NULL,"task status");pid_t group=0;
    while(fgets(line,sizeof(line),f))if(sscanf(line,"Tgid: %d",&group)==1)break;
    require(fclose(f)==0 && group>0,"task group");
    slot->tid=tid;slot->group=group;
    for(size_t i=0;i<4096;i++)if(tasks[i].tid && tasks[i].group==group && tasks[i].image){slot->image=tasks[i].image;break;}
    if(!slot->image)image_record(slot,"first");
    require(fprintf(journal,"T %d %d %d\n",tid,group,slot->image)>0,"task birth");
    return slot;
}

static void resume(pid_t pid,int sig){if(ptrace(PTRACE_CONT,pid,0,sig)<0 && errno!=ESRCH)require(0,"resume");}

int main(int argc,char **argv) {
    require(argc>=6,"MODE DIRECTORY AUTHENTICATED_OWNER CRATE PROGRAM ...");mode=argv[1];directory=argv[2];owner=argv[4];
    require(strcmp(mode,"owner")==0 || strcmp(mode,"whole")==0 || strcmp(mode,"roster")==0,"registered counter role");
    require(stat(argv[3],&owner_exe)==0 && S_ISREG(owner_exe.st_mode),"original owner executable");
    char file[4096];int used=snprintf(file,sizeof(file),"%s/epochs.tsv",directory);require(used>0 && (size_t)used<sizeof(file),"journal path");
    journal=fopen(file,"wx");require(journal!=NULL && fprintf(journal,"M %d %"PRIu64"\n",getpid(),now())>0,"journal");
    leader=fork();require(leader>=0,"fork");if(!leader){require(ptrace(PTRACE_TRACEME,0,0,0)==0,"trace");raise(SIGSTOP);execvp(argv[5],argv+5);_exit(127);}
    int status,code=-1;require(waitpid(leader,&status,0)==leader && WIFSTOPPED(status),"initial stop");
    require(ptrace(PTRACE_SETOPTIONS,leader,0,PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_TRACEEXIT|PTRACE_O_EXITKILL)==0,"exec custody");
    lookup(leader,1);resume(leader,0);
    for(;;){pid_t pid=waitpid(-1,&status,__WALL);if(pid<0){if(errno==EINTR)continue;require(errno==ECHILD,"complete process tree");break;}
        if(WIFEXITED(status)||WIFSIGNALED(status)){struct task*t=lookup(pid,0);require(t!=NULL,"tracked exit");
            require(fprintf(journal,"X %d %d %d %d\n",pid,t->group,t->image,status)>0,"task exit");memset(t,0,sizeof(*t));
            if(pid==leader)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
            continue;}
        require(WIFSTOPPED(status),"task stopped");struct task*t=lookup(pid,1);int event=status>>16,sig=WSTOPSIG(status);
        if(event==PTRACE_EVENT_EXEC)image_record(t,"exec");
        if(event==PTRACE_EVENT_EXIT && t->image==selected)driver_at_exit(t);
        resume(pid,event||sig==SIGSTOP||sig==SIGTRAP?0:sig);
    }
    require(code>=0 && images>=2,"complete root");
    uint64_t count[3]={0,0,0};
    if(event_fd>=0){require(read(event_fd,count,sizeof(count))==sizeof(count) && close(event_fd)==0,"complete final inherited hardware read");}
    require(fprintf(journal,"F %d %d %d %"PRIu64" %"PRIu64" %"PRIu64"\n",code,selected,measured,count[0],count[1],count[2])>0 && fclose(journal)==0,"result final");
    return code;
}
