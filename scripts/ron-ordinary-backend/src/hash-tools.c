/* Price all three tool files, including open/read/hash/close. Earlier manifests bind
   each physical input to its signed SHA-256. This component prices BLAKE3 bytes only. */
#include "blake3.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int n,char **args) {
  if(n!=4)return 1;
  for(int i=1;i<n;i++){
    int fd=open(args[i],O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    struct stat before,after;
    if(fd<0||fstat(fd,&before)||!S_ISREG(before.st_mode))return 2;
    unsigned char buf[262144],h[BLAKE3_OUT_LEN];ssize_t r;blake3_hasher v;blake3_hasher_init(&v);
    while((r=read(fd,buf,sizeof(buf)))>0)blake3_hasher_update(&v,buf,(size_t)r);
    if(r<0||fstat(fd,&after)||before.st_size!=after.st_size||
       before.st_ctim.tv_sec!=after.st_ctim.tv_sec||before.st_ctim.tv_nsec!=after.st_ctim.tv_nsec)return 3;
    blake3_hasher_finalize(&v,h,sizeof(h));close(fd);
    for(size_t j=0;j<sizeof(h);j++)printf("%02x",h[j]);printf("  %s\n",args[i]);
  }
  return 0;
}
