#include <dirent.h>
#include <openssl/sha.h>
static void hash_raw(const void *raw, size_t bytes, char out[65]) {
    unsigned char d[32]; if (!SHA256(raw,bytes,d)) _exit(125);
    for (int i=0;i<32;i++) sprintf(out+i*2,"%02x",d[i]);
}
/* All local wire bytes are explicit fields. No structure padding may enter a receipt. */
#include <stddef.h>
struct inherited_fd {
    uint64_t device, inode;
    int32_t number;
    uint16_t type, access;
};
_Static_assert(sizeof(struct inherited_fd)==24 &&
    offsetof(struct inherited_fd,device)==0 && offsetof(struct inherited_fd,inode)==8 &&
    offsetof(struct inherited_fd,number)==16 && offsetof(struct inherited_fd,type)==20 &&
    offsetof(struct inherited_fd,access)==22,"complete padding-free FD record");
