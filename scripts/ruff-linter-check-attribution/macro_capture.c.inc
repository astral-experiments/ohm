/* Off-clock replay only. The caller injects this after recording a real stopped exec.
 * The parent starts Cargo with an allowlisted environment. Private bytes are
 * never placed in the uploaded receipt or used by the measured observer. */
static void capture_compiler(pid_t tid, const char *executable, int id, const char *trigger) {
    if (strcmp(executable, OHM_SIGNED_RUSTC) || strcmp(trigger, "exec")) return;
    char path[128];
    output(path,sizeof(path),"/proc/%d/cmdline",tid);
    int fd=open(path,O_RDONLY|O_CLOEXEC); require(fd>=0,"private argv");
    const size_t cap=1024*1024;
    char *argv=malloc(cap); require(argv!=NULL,"private argv storage");
    size_t len=0; ssize_t n;
    while ((n=read(fd,argv+len,cap-len))>0) { len+=(size_t)n; require(len<cap,"private argv size"); }
    require(n==0 && len>0 && !argv[len-1] && !close(fd),"private argv end");
    const char *owner=0;
    for (size_t i=0;i<len;i+=strlen(argv+i)+1) if (!strcmp(argv+i,"--crate-name")) {
        size_t next=i+strlen(argv+i)+1; require(next<len && !owner,"private crate name");owner=argv+next;
    }
    if (!owner || (strcmp(owner,"ruff_macros") && strcmp(owner,"ruff_linter"))) { free(argv);return; }
    char folder[4096],name[4096]; int k=snprintf(folder,sizeof(folder),"%s/%s",OHM_PRIVATE_ROOT,owner);
    require(k>0 && (size_t)k<sizeof(folder) && !mkdir(folder,0700),"one original compiler");
    k=snprintf(name,sizeof(name),"%s/record",folder);require(k>0 && (size_t)k<sizeof(name),"receipt length");
    FILE *record=fopen(name,"wx");require(record!=NULL && fprintf(record,"%d\n",id)>0 && !fclose(record),"compiler record number");
    output(path,sizeof(path),"/proc/%d/cwd",tid);char cwd[4096];n=readlink(path,cwd,sizeof(cwd)-1);require(n>0 && (size_t)n<sizeof(cwd)-1,"compiler cwd");cwd[n]=0;
    k=snprintf(name,sizeof(name),"%s/cwd",folder);require(k>0 && (size_t)k<sizeof(name),"cwd length");
    record=fopen(name,"wx");require(record!=NULL && fputs(cwd,record)>=0 && !fclose(record),"compiler cwd record");
    output(path,sizeof(path),"/proc/%d/environ",tid);fd=open(path,O_RDONLY|O_CLOEXEC);require(fd>=0,"compiler environment");
    k=snprintf(name,sizeof(name),"%s/environment",folder);require(k>0 && (size_t)k<sizeof(name),"env length");
    record=fopen(name,"wx");require(record!=NULL,"private env output");len=0;
    while ((n=read(fd,argv,cap))>0){len+=(size_t)n;require(len<cap && fwrite(argv,1,(size_t)n,record)==(size_t)n,"private env size");}
    require(n==0 && len>0 && !close(fd) && !fclose(record),"complete private env");free(argv);
}
