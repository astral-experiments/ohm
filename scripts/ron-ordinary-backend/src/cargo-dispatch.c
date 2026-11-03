// Diagnostic only. Cargo keeps its own compiler path, version queries and build-directory policy.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern char **environ;
typedef int (*exec_env)(const char *, char *const [], char *const []);
typedef int (*exec_plain)(const char *, char *const []);
typedef int (*spawn_fn)(pid_t *, const char *, const posix_spawn_file_actions_t *, const posix_spawnattr_t *, char *const [], char *const []);
static exec_env orig_execve, orig_execvpe;
static exec_plain orig_execvp, orig_execv;
static spawn_fn orig_spawn, orig_spawnp;
static const char *receiver;
static bool enabled;

__attribute__((constructor)) static void setup(void) {
    orig_execve=(exec_env)dlsym(RTLD_NEXT,"execve"); orig_execvpe=(exec_env)dlsym(RTLD_NEXT,"execvpe");
    orig_execv=(exec_plain)dlsym(RTLD_NEXT,"execv"); orig_execvp=(exec_plain)dlsym(RTLD_NEXT,"execvp");
    orig_spawn=(spawn_fn)dlsym(RTLD_NEXT,"posix_spawn"); orig_spawnp=(spawn_fn)dlsym(RTLD_NEXT,"posix_spawnp");
    const char *cargo=getenv("OHM_CAPTURE_CARGO"),*self=getenv("OHM_CAPTURE_DISPATCH"),*ld=getenv("LD_PRELOAD");
    if(!cargo||!self||!ld||strcmp(ld,self))return;
    struct stat here,desired;
    if(stat("/proc/self/exe",&here)||stat(cargo,&desired)||here.st_dev!=desired.st_dev||here.st_ino!=desired.st_ino)return;
    receiver=getenv("OHM_CAPTURE_RECEIVER");
    if(receiver && receiver[0]=='/') {
        enabled=true;
        // The already-loaded image intercepts only Cargo's spawn calls. Its children inherit no preload.
        unsetenv("LD_PRELOAD");
    }
}

static bool change(const char *file,char *const av[],char **out) {
    if(!enabled)return false;
    const char *base=strrchr(file,'/');base=base?base+1:file;
    if(strcmp(base,"rustc"))return false;
    int len=0;bool ron=false;
    while(av[len]&&len<2044) {
        if(!strcmp(av[len],"--crate-name")&&av[len+1]&&!strcmp(av[len+1],"ron"))ron=true;
        len++;
    }
    if(!ron||len==2044)return false;
    out[0]=(char*)receiver;out[1]=(char*)file;
    for(int i=0;i<=len;i++)out[i+2]=av[i];
    return true;
}

int execve(const char *p,char *const av[],char *const env[]) {
    char *v[2048];return change(p,av,v)?orig_execve(receiver,v,env):orig_execve(p,av,env);
}
int execvpe(const char *p,char *const av[],char *const env[]) {
    char *v[2048];return change(p,av,v)?orig_execve(receiver,v,env):orig_execvpe(p,av,env);
}
int execvp(const char *p,char *const av[]) {
    char *v[2048];return change(p,av,v)?orig_execve(receiver,v,environ):orig_execvp(p,av);
}
int execv(const char *p,char *const av[]) {
    char *v[2048];return change(p,av,v)?orig_execve(receiver,v,environ):orig_execv(p,av);
}
int posix_spawn(pid_t *pid,const char *p,const posix_spawn_file_actions_t *fa,const posix_spawnattr_t *attr,char *const av[],char *const env[]) {
    char *v[2048];return change(p,av,v)?orig_spawn(pid,receiver,fa,attr,v,env):orig_spawn(pid,p,fa,attr,av,env);
}
int posix_spawnp(pid_t *pid,const char *p,const posix_spawn_file_actions_t *fa,const posix_spawnattr_t *attr,char *const av[],char *const env[]) {
    char *v[2048];return change(p,av,v)?orig_spawn(pid,receiver,fa,attr,v,env):orig_spawnp(pid,p,fa,attr,av,env);
}
