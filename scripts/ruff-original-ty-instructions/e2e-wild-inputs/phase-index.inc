struct row {const char *path; uint32_t position;};
static int by_path(const void *lhs,const void *rhs) {
    return strcmp(((const struct row*)lhs)->path,((const struct row*)rhs)->path);
}
static FILE *compact_inputs(FILE *f) {
    struct stat st;
    if (!f||fstat(fileno(f),&st)||st.st_size<=0||st.st_size>16*1024*1024) return NULL;
    size_t size=(size_t)st.st_size;
    char *raw=malloc(size),*unique=malloc(size);
    if (!raw||!unique||fread(raw,1,size,f)!=size||raw[size-1]||fclose(f))return NULL;
    size_t count=0;for(size_t i=0;i<size;i++)if(!raw[i])count++;
    if(!count||count>100000)return NULL;
    struct row *rows=calloc(count,sizeof(*rows));uint32_t *indices=calloc(count,sizeof(*indices));
    if(!rows||!indices)return NULL;
    char *p=raw;for(size_t i=0;i<count;i++){if(*p!='/')return NULL;rows[i]=(struct row){p,(uint32_t)i};p+=strlen(p)+1;}
    qsort(rows,count,sizeof(*rows),by_path);
    uint32_t n=0;size_t used=0;
    for(size_t i=0;i<count;i++){
        if(!i||strcmp(rows[i-1].path,rows[i].path)){size_t len=strlen(rows[i].path)+1;memcpy(unique+used,rows[i].path,len);used+=len;n++;}
        indices[rows[i].position]=n-1;
    }
    unsigned char digest[EVP_MAX_MD_SIZE];unsigned dlen=0;
    if(EVP_Digest(indices,count*sizeof(*indices),digest,&dlen,EVP_sha256(),NULL)!=1||dlen!=32)return NULL;
    fprintf(stderr,"QA_INDEX %zu %u %zu %zu ",count,n,count*sizeof(*indices),used);
    for(unsigned i=0;i<dlen;i++)fprintf(stderr,"%02x",digest[i]);
    fputc('\n',stderr);free(raw);free(rows);free(indices);
    return fmemopen(unique,used,"rb");
}
