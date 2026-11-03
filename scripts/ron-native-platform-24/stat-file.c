#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fsverity.h>
#include <linux/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    int fd=open(argv[1],O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return 3;
    struct statx st={0};struct statfs fs;
    if(statx(fd,"",AT_EMPTY_PATH,STATX_BASIC_STATS|STATX_MNT_ID,&st)||fstatfs(fd,&fs))return 4;
    unsigned char data[sizeof(struct fsverity_digest)+64]={0};
    struct fsverity_digest *v=(void *)data;v->digest_size=64;
    errno=0;int verity=ioctl(fd,FS_IOC_MEASURE_VERITY,v),ve=errno;
    errno=0;int seals=fcntl(fd,F_GET_SEALS),se=errno;
    printf("{\"dev\":[%u,%u],\"ino\":%ju,\"mnt_id\":%ju,\"uid\":%u,\"mode\":%u,\"fstype\":%lu,\"verity\":[%d,%d],\"seals\":[%d,%d]}\n",st.stx_dev_major,st.stx_dev_minor,(uintmax_t)st.stx_ino,(uintmax_t)st.stx_mnt_id,st.stx_uid,st.stx_mode,(unsigned long)fs.f_type,verity,ve,seals,se);
    close(fd);return 0;
}
