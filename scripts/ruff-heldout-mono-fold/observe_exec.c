/* Record successful execs in the ordinary Cargo process tree. The observer never reads env or rewrites arguments. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void check(int ok,const char *what) { if(!ok){perror(what);exit(125);} }
static void continued(pid_t pid,int sig) { if(ptrace(PTRACE_CONT,pid,0,sig)<0&&errno!=ESRCH)check(0,"resume"); }
static void record(const char *out,int seq,pid_t pid) {
    char source[64],target[4096],buffer[16384];
    check(snprintf(source,sizeof(source),"/proc/%d/exe",pid)>0,"executable path");
    ssize_t n=readlink(source,target,sizeof(target)-1);check(n>0 && (size_t)n<sizeof(target)-1,"read executable");target[n]=0;
    struct stat st;check(stat(source,&st)==0,"stat executable");
    char filename[4096];int needed=snprintf(filename,sizeof(filename),"%s/%05d.nul",out,seq);check(needed>0 && (size_t)needed<sizeof(filename),"output path");
    FILE *file=fopen(filename,"wx");check(file!=NULL,"new argv receipt");
    check(fprintf(file,"%d%c%ju%c%ju%c%s%c",pid,0,(uintmax_t)st.st_dev,0,(uintmax_t)st.st_ino,0,target,0)>0,"write executable identity");
    check(snprintf(source,sizeof(source),"/proc/%d/cmdline",pid)>0,"argv path");int fd=open(source,O_RDONLY|O_CLOEXEC);check(fd>=0,"open argv");size_t total=0;
    while((n=read(fd,buffer,sizeof(buffer)))>0) {total+=(size_t)n;check(total<=8u<<20,"bounded argv");check(fwrite(buffer,1,(size_t)n,file)==(size_t)n,"record argv");}
    check(n==0 && total>0 && close(fd)==0 && fclose(file)==0,"complete receipt");
}
int main(int argc,char **argv) {
    check(argc>=4,"OUTPUT_DIR PROGRAM ARGS");pid_t root=fork();check(root>=0,"fork");
    if(!root){check(ptrace(PTRACE_TRACEME,0,0,0)==0,"trace child");raise(SIGSTOP);execvp(argv[2],argv+2);_exit(127);}
    int status=0,seq=0,code=-1;check(waitpid(root,&status,0)==root && WIFSTOPPED(status),"initial stop");
    check(ptrace(PTRACE_SETOPTIONS,root,0,PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|PTRACE_O_EXITKILL)==0,"install observer");continued(root,0);
    for(;;){pid_t pid=waitpid(-1,&status,__WALL);if(pid<0){if(errno==EINTR)continue;check(errno==ECHILD,"wait tree");break;}
        if(WIFEXITED(status)||WIFSIGNALED(status)){if(pid==root)code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);continue;}
        check(WIFSTOPPED(status),"unexpected wait");int event=status>>16,sig=WSTOPSIG(status);
        if(event==PTRACE_EVENT_EXEC)record(argv[1],++seq,pid);
        continued(pid,event||sig==SIGSTOP||sig==SIGTRAP?0:sig);
    }
    check(seq>0 && code>=0,"complete process tree");return code;
}
