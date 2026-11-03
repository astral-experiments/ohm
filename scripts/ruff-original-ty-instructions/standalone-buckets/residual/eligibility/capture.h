/* Save the one real compiler's inputs privately at its normal exec stop. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static void bound(int ok) { if (!ok) { perror("private compiler-input capture"); _exit(117); } }
static size_t content(char *dest,size_t bytes,const char *file) {
    int fd=open(file,O_RDONLY|O_CLOEXEC);bound(fd>=0);size_t used=0;ssize_t n;
    while ((n=read(fd,dest+used,bytes-used))>0) { used+=(size_t)n;bound(used<bytes); }
    bound(n==0 && close(fd)==0);return used;
}
static void private_bytes(const char *name,const char *buf,size_t n) {
    char path[8192];int size=snprintf(path,sizeof(path),"%s/%s",PRIVATE_ENV,name);
    bound(size>0 && (size_t)size<sizeof(path));int fd=open(path,O_WRONLY|O_CLOEXEC|O_CREAT|O_EXCL,0600);
    bound(fd>=0);while(n) { ssize_t c=write(fd,buf,n);bound(c>0);buf+=c;n-=(size_t)c; }bound(close(fd)==0);
}
static void capture_owner(int tid,const char *reason) {
    if(strcmp(reason,"exec"))return;
    char path[128];int n=snprintf(path,sizeof(path),"/proc/%d/exe",tid);bound(n>0 && (size_t)n<sizeof(path));
    struct stat st,want;bound(stat(path,&st)==0 && stat(REAL_RUSTC,&want)==0);
    if(st.st_dev!=want.st_dev || st.st_ino!=want.st_ino)return;
    char *buf=malloc(1u<<20);bound(buf!=NULL);snprintf(path,sizeof(path),"/proc/%d/cmdline",tid);
    size_t size=content(buf,1u<<20,path);int found=0,last=0;
    for(size_t i=0;i<size;) { char *p=memchr(buf+i,0,size-i);bound(p!=NULL);if(last && !strcmp(buf+i,"ty_project"))found++;last=!strcmp(buf+i,"--crate-name");i=(size_t)(p-buf)+1; }
    if(found) {
        bound(found==1);private_bytes("argv",buf,size);snprintf(path,sizeof(path),"/proc/%d/environ",tid);
        size=content(buf,1u<<20,path);private_bytes("environment",buf,size);snprintf(path,sizeof(path),"/proc/%d/cwd",tid);
        ssize_t k=readlink(path,buf,1u<<20);bound(k>0 && k<(1<<20));private_bytes("cwd",buf,(size_t)k);
    }
    free(buf);
}
