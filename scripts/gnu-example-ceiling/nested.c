#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void need(int ok){if(!ok)_exit(95);}
static void spin(unsigned long n){if(n)__asm__ volatile("1: dec %0\n\tjne 1b" : "+r"(n) : : "cc");}
static void *thread(void *arg){spin(*(const unsigned long*)arg);return NULL;}
static void finish(pid_t p,int sig){int st;need(p>0);pid_t got;do{got=waitpid(p,&st,0);}while(got<0 && errno==EINTR);
    need(got==p && (sig?(WIFSIGNALED(st) && WTERMSIG(st)==sig):(WIFEXITED(st) && WEXITSTATUS(st)==0)));}
static pid_t next(const char *dir,const char *role,const char *name,const char *loops){
    pid_t p=fork();need(p>=0);if(p)return p;
    char path[PATH_MAX],source[200],target[PATH_MAX];need(snprintf(path,sizeof(path),"%s/%s",dir,role)<(int)sizeof(path));
    need(snprintf(source,sizeof(source),"crates/ruff_annotate_snippets/examples/%s.rs",name)<(int)sizeof(source));
    need(snprintf(target,sizeof(target),"%s/%s",dir,name)<(int)sizeof(target));
    if(!strcmp(role,"rustc"))execl(path,path,dir,name,loops,"--crate-name",name,"--crate-type","bin","--emit=dep-info,link","--out-dir",dir,"-C","incremental=/cal/target/debug/incremental/aa",source,(char*)0);
    else if(!strcmp(role,"outside"))execl(path,path,dir,name,loops,(char*)0);
    else execl(path,path,dir,name,loops,"-o",target,(char*)0);
    _exit(97);
}
int main(int argc,char **argv){
    need(argc>=4);const char *dir=argv[1],*name=argv[2],*it=argv[3],*role=strrchr(argv[0],'/');need(role!=NULL);++role;
    unsigned long n=strtoul(it,NULL,10),factor=!strcmp(name,"alpha")?1:2;
    if(!strcmp(role,"root")){
        pid_t first=next(dir,"rustc","alpha",it),second=next(dir,"rustc","beta",it),more=next(dir,"outside","ignore",it);
        pid_t fast=fork();need(fast>=0);if(!fast)_exit(0);
        pid_t signal_child=fork();need(signal_child>=0);if(!signal_child){raise(SIGTERM);_exit(94);}
        finish(fast,0);finish(signal_child,SIGTERM);finish(first,0);finish(second,0);finish(more,0);
    }else if(!strcmp(role,"rustc")){spin(factor*n);finish(next(dir,"cc",name,it),0);}
    else if(!strcmp(role,"cc")){spin(2*factor*n);finish(next(dir,"collect2",name,it),0);}
    else if(!strcmp(role,"collect2")){spin(3*factor*n);finish(next(dir,"wild",name,it),0);}
    else if(!strcmp(role,"wild")){
        spin(4*factor*n);pid_t p=fork();need(p>=0);if(!p){spin(5*factor*n);pthread_t t[2];unsigned long work=6*factor*n;
            for(int i=0;i<2;++i)need(!pthread_create(&t[i],NULL,thread,&work));
            for(int i=0;i<2;++i)need(!pthread_join(t[i],NULL));
            _exit(0);}
        finish(p,0);
    }else if(!strcmp(role,"outside"))spin(7*n);
    else return 96;
    return 0;
}
