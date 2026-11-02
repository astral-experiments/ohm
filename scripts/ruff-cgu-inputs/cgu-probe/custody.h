#include <dirent.h>
#include <openssl/sha.h>
static void hash_raw(const void *raw, size_t bytes, char out[65]) {
    unsigned char d[32]; if (!SHA256(raw,bytes,d)) _exit(125);
    for (int i=0;i<32;i++) sprintf(out+i*2,"%02x",d[i]);
}
struct inherited_fd { int number; uint64_t device,inode; uint32_t type; };
