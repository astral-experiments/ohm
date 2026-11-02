/* A QA-only glibc audit object. Only the real selected Rust driver may replace
 * the one registered dlopen. Normal file reads, including rustc metadata,
 * always use Cargo's original product. Other images disable auditing. */
#define _GNU_SOURCE
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

unsigned int la_version(unsigned int version) {
    char exe[4096], args[1024*1024];ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
    if(n<=0 || (size_t)n>=sizeof(exe)-1)return 0;
    exe[n]=0;if(strcmp(exe,OHM_SIGNED_RUSTC))return 0;
    int fd=open("/proc/self/cmdline",O_RDONLY|O_CLOEXEC);if(fd<0)return 0;
    ssize_t len=0;while((n=read(fd,args+len,sizeof(args)-(size_t)len))>0)len+=n;
    close(fd);if(n || len<=0 || (size_t)len==sizeof(args) || args[len-1])return 0;
    for(size_t i=0;i<(size_t)len;i+=strlen(args+i)+1)if(!strcmp(args+i,"--crate-name")){
        i+=strlen(args+i)+1;return i<(size_t)len && !strcmp(args+i,"ruff_linter") && version>=LAV_CURRENT ? LAV_CURRENT : 0;
    }
    return 0;
}
char *la_objsearch(const char *name, uintptr_t *cookie, unsigned int flag) {
    (void)cookie;
    if(flag==LA_SER_ORIG && !strcmp(name,OHM_ORIGINAL_DSO))return (char*)OHM_LOADED_DSO;
    return (char*)name;
}
unsigned int la_objopen(struct link_map *map,Lmid_t lmid,uintptr_t *cookie) {
    (void)lmid;(void)cookie;
    if(!strcmp(map->l_name,OHM_LOADED_DSO)){
        struct stat st;char data[256];int fd=open(OHM_OPEN_RECEIPT,O_WRONLY|O_CREAT|O_APPEND|O_NOFOLLOW|O_CLOEXEC,0600);
        if(fd<0 || stat(map->l_name,&st))_exit(124);
        int n=snprintf(data,sizeof(data),"%d %ju %ju %ju\n",getpid(),(uintmax_t)st.st_dev,(uintmax_t)st.st_ino,(uintmax_t)st.st_size);
        if(n<=0 || (size_t)n>=sizeof(data) || write(fd,data,(size_t)n)!=n || close(fd))_exit(124);
    }
    return 0;
}
