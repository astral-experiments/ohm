/* Enter Valgrind exactly once, for the already selected and authenticated
 * Cargo child at the original ELF exec stop. Linux x86-64 glibc only. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "custody.h"

static void need(int ok,const char *msg){
    if(!ok) {dprintf(2,"selected compiler diagnostic launcher: %s\n",msg);_exit(125);}
}
static const char *env_value(char **env,const char *name){
    size_t n=strlen(name);for(;*env;++env)if(!strncmp(*env,name,n)&&(*env)[n]=='=')return *env+n+1;
    return NULL;
}
static size_t read_file(int d,const char *name,void *buffer,size_t maximum){
    int f=openat(d,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);need(f>=0,"open staged custody record");
    size_t n=0;while(n<maximum){ssize_t k=read(f,(char*)buffer+n,maximum-n);if(k<0&&errno==EINTR)continue;need(k>=0,"read staged custody record");if(!k)break;n+=k;}
    char extra;need(read(f,&extra,1)==0&&close(f)==0,"bounded complete custody record");return n;
}
static char *pack(char **v,size_t *length,size_t *count){
    *length=*count=0;for(size_t i=0;v[i];++i){size_t n=strlen(v[i])+1;need(n<=2u<<20&&*length+n<=4u<<20,"registered input size");*length+=n;++*count;}
    char *out=malloc(*length);need(out!=NULL,"pack input strings");size_t pos=0;
    for(size_t i=0;v[i];++i){size_t n=strlen(v[i])+1;memcpy(out+pos,v[i],n);pos+=n;}return out;
}
int __libc_start_main(int (*mainfn)(int,char**,char**),int argc,char **argv,
    void (*init)(void),void (*fini)(void),void (*ld_fini)(void),void *stack_end){
    (void)mainfn;(void)init;(void)fini;(void)ld_fini;(void)stack_end;
    char **env=argv+argc+1;size_t preloads=0;const char prefix[]="OHM_CGUR_LOADER=";
    for(size_t i=0;env[i];++i){
        if(!strncmp(env[i],"LD_PRELOAD=",11)){
            size_t suffix=strlen(env[i])+1;
            char *full=malloc(sizeof(prefix)-1+suffix);need(full!=NULL,"restore private route slot");
            memcpy(full,prefix,sizeof(prefix)-1);memcpy(full+sizeof(prefix)-1,env[i],suffix);
            env[i]=full;++preloads;
        }
    }
    need(preloads==1&&!env_value(env,"LD_PRELOAD")&&!env_value(env,"RUSTC_WRAPPER")&&!env_value(env,"RUSTC_WORKSPACE_WRAPPER"),"restore original flags and loader environment");
    const char *stage=env_value(env,"OHM_CGUR_STAGE"),*signed_rustc=env_value(env,"OHM_CGUR_SIGNED"),*vglib=env_value(env,"VALGRIND_LIB");
    need(stage&&*stage=='/'&&signed_rustc&&*signed_rustc=='/'&&vglib&&*vglib=='/'&&!strchr(stage,'%'),"absolute registered paths");
    struct stat self,sig,arg0;need(!stat("/proc/self/exe",&self)&&!stat(signed_rustc,&sig)&&!stat(argv[0],&arg0)&&self.st_dev==sig.st_dev&&self.st_ino==sig.st_ino&&self.st_dev==arg0.st_dev&&self.st_ino==arg0.st_ino,"original signed program and argv[0]");
    int count=0;for(int i=1;i+1<argc;i++)if(!strcmp(argv[i],"--crate-name")&&!strcmp(argv[i+1],"ruff_workspace"))++count;
    need(count==1,"unique selected crate name");
    char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/ruff_workspace",stage);need(n>0&&n<(int)sizeof(path),"bounded stage");int d=open(path,O_DIRECTORY|O_RDONLY|O_NOFOLLOW|O_CLOEXEC);need(d>=0,"open selected stage");
    size_t envlen,envcount,avlen,avcount;char *en=pack(env,&envlen,&envcount),*av=pack(argv,&avlen,&avcount),got[65],want[65];
    hash_raw(en,envlen,got);need(read_file(d,"original-env.sha256",want,64)==64&&!memcmp(got,want,64),"all original environment bytes restored in order");
    char *original=malloc(avlen);need(original&&read_file(d,"original.nul",original,avlen)==avlen&&avcount==(size_t)argc&&!memcmp(av,original,avlen),"all original signed argv bytes in order");
    struct inherited_fd rows[512];size_t fdbytes=read_file(d,"original-fds.bin",rows,sizeof(rows));need(fdbytes%sizeof(*rows)==0,"whole descriptor inventory");size_t nf=fdbytes/sizeof(*rows);need(nf>=3,"selected inherited descriptors");
    for(size_t i=0;i<nf;i++){struct stat b;need(!fstat(rows[i].number,&b)&&b.st_dev==rows[i].device&&b.st_ino==rows[i].inode&&(b.st_mode&S_IFMT)==rows[i].type&&(fcntl(rows[i].number,F_GETFL)&O_ACCMODE)==rows[i].access,"same original descriptor number, file identity and read/write mode");}
    int receipt=openat(d,"launch.json",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);need(receipt>=0,"unique launch receipt");
    dprintf(receipt,"{\"pid\":%d,\"argc\":%zu,\"argv_bytes\":%zu,\"envc\":%zu,\"env_bytes\":%zu,\"env_sha256\":\"%s\",\"fds\":[",getpid(),avcount,avlen,envcount,envlen,got);
    for(size_t i=0;i<nf;i++)dprintf(receipt,"%s[%d,%"PRIu64",%"PRIu64",%u,%u]",i?",":"",rows[i].number,rows[i].device,rows[i].inode,rows[i].type,rows[i].access);
    dprintf(receipt,"]}\n");need(!close(receipt)&&!unlinkat(d,"original-fds.bin",0)&&!close(d),"remove private descriptor handoff and close audit receipts");
    char log[PATH_MAX];n=snprintf(log,sizeof(log),"--log-file=%s/cgu.log",path);need(n>0&&n<(int)sizeof(log),"bounded diagnostic log");
    char **run=calloc((size_t)argc+7,sizeof(*run));need(run!=NULL,"Valgrind argument vector");
    run[0]="/usr/bin/valgrind";run[1]="--tool=cgured";run[2]="--quiet";run[3]="--trace-children=no";run[4]="--vex-guest-chase=no";run[5]=log;for(int i=0;i<argc;i++)run[6+i]=argv[i];
    execve(run[0],run,env);need(0,"exec registered Valgrind diagnostic");return 125;
}
