#include <fcntl.h>
#include <openssl/evp.h>
#include <limits.h>

static void canonical_at_exec(const char *record, const char *reason,
                              const char *image, int tgid, int epoch) {
    if (strcmp(reason, "exec") != 0) return;
    const char *base = strrchr(image, '/');
    if (!base) return;
    ++base;
    if (strcmp(base, "rustc") && !strstr(base, "linux-gnu-gcc") &&
        strcmp(base, "collect2") && strcmp(base, "ld.bfd")) return;

    FILE *file = fopen(record, "rb");
    require(file != NULL, "read actual command");
    char *word = NULL;
    size_t len = 0;
    int owner = 0, n = 0;
    while (getdelim(&word, &len, 0, file) > 0) {
        if (n++ < 4) continue;
        if (!strcmp(word, CANONICAL) || !strcmp(word, CANONICAL ".rlink") ||
            (!strcmp(base,"rustc") && !strcmp(word, "extra-filename=-f5c6198f896cf7b0"))) owner = 1;
    }
    free(word);
    require(!ferror(file) && fclose(file)==0, "complete owner argv");
    if (!owner) return;

    char destination[PATH_MAX];
    int size = snprintf(destination, sizeof(destination), "%s/canonical-%d.tsv",directory,epoch);
    require(size>0 && size<(int)sizeof(destination), "canonical receipt path");
    FILE *receipt = fopen(destination, "wx");
    require(receipt != NULL, "create canonical receipt");
    int fd=open(CANONICAL,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0){
        int error=errno;
        require(fprintf(receipt, "%d\t%d\t%s\tabsent\t%d\t%s\n",epoch,tgid,image,error,CANONICAL)>0 &&
                fclose(receipt)==0, "absent output receipt");
        return;
    }
    struct stat before, after, linked;
    require(fstat(fd,&before)==0 && S_ISREG(before.st_mode) &&
            before.st_size>0 && before.st_size<(512ll<<20), "bounded canonical regular file");
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();
    require(ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),NULL)==1,"SHA256 begin");
    unsigned char buffer[65536], digest[EVP_MAX_MD_SIZE];
    ssize_t amount;
    off_t total=0;
    while((amount=read(fd,buffer,sizeof(buffer)))>0){
        total+=amount;require(total<=before.st_size && EVP_DigestUpdate(ctx,buffer,(size_t)amount)==1,"read all existing output bytes");
    }
    unsigned int hashlen=0;
    require(amount==0 && total==before.st_size && EVP_DigestFinal_ex(ctx,digest,&hashlen)==1 && hashlen==32,"finish output SHA256");
    EVP_MD_CTX_free(ctx);
    int same=fstat(fd,&after)==0 && lstat(CANONICAL,&linked)==0 &&
        after.st_dev==before.st_dev && after.st_ino==before.st_ino &&
        linked.st_dev==before.st_dev && linked.st_ino==before.st_ino &&
        after.st_size==before.st_size && before.st_ctim.tv_sec==after.st_ctim.tv_sec &&
        before.st_ctim.tv_nsec==after.st_ctim.tv_nsec;
    require(fprintf(receipt,"%d\t%d\t%s\tpresent\t%d\t%ju\t%ju\t%ju\t%ju\t%jo\t",
                    epoch,tgid,image,same,(uintmax_t)before.st_dev,(uintmax_t)before.st_ino,
                    (uintmax_t)before.st_nlink,(uintmax_t)total,(uintmax_t)before.st_mode)>0,"output receipt");
    for(unsigned int i=0;i<hashlen;i++)require(fprintf(receipt,"%02x",digest[i])==2,"digest hex");
    require(fprintf(receipt,"\t%s\n",CANONICAL)>0 && close(fd)==0 && fclose(receipt)==0,"end output receipt");
}
