#include <fcntl.h>
#include <sys/ioctl.h>
#include <limits.h>

static void save_file(const char *src, const char *dst) {
    char b[16384]; int input=open(src,O_RDONLY|O_CLOEXEC), out=open(dst,O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600);
    require(input>=0 && out>=0,"capture open");
    size_t used=0;ssize_t n;
    while ((n=read(input,b,sizeof(b)))>0) {used+=(size_t)n;require(used<1024*1024 && write(out,b,n)==n,"capture write");}
    require(n==0 && close(input)==0 && close(out)==0,"capture finish");
}

static char capture_dir[2048];

static const char *capture_path(const char *name) {
    static char path[4096];
    int n=snprintf(path,sizeof(path),"%s/%s",capture_dir,name);
    require(n>0 && (size_t)n<sizeof(path),"capture path");
    return path;
}

static void capture_link(pid_t pid, const char *exe, const char *trigger, const char *args) {
    if(strcmp(trigger,"exec")||!strstr(exe,"/wild-ld/ld.bfd"))return;
    FILE *f=fopen(args,"rb");require(f!=NULL,"open argv");
    char *word=NULL;size_t len=0,i=0;int target=0,output=0;char syms[4096]="";
    while(getdelim(&word,&len,0,f)>0){
        if(i++<4)continue;
        const char *base=strrchr(word,'/');base=base?base+1:word;
        if(output&&!strcmp(base,"e2e-f5c6198f896cf7b0"))target=1;
        output=!strcmp(word,"-o");
        if(!strcmp(base,"symbols.o")){require(!syms[0]&&strlen(word)<sizeof(syms),"single symbols.o");strcpy(syms,word);}
    }
    free(word);require(!ferror(f)&&fclose(f)==0,"read argv");
    int len_dir=target?snprintf(capture_dir,sizeof(capture_dir),"%s",QA_CAPTURE):
        snprintf(capture_dir,sizeof(capture_dir),"%s/role-%d",QA_CAPTURE,pid);
    require(len_dir>0 && (size_t)len_dir<sizeof(capture_dir),"role directory");
    if(!target)require(mkdir(capture_dir,0700)==0,"new role directory");
    require(syms[0]=='/',"absolute symbols object");save_file(syms,capture_path("symbols.o"));save_file(args,capture_path("argv.nul"));
    char path[100],dst[4096];snprintf(path,sizeof(path),"/proc/%d/environ",pid);save_file(path,capture_path("env.nul"));
    snprintf(path,sizeof(path),"/proc/%d/cwd",pid);ssize_t n=readlink(path,dst,sizeof(dst)-1);require(n>0 && n<(ssize_t)sizeof(dst)-1,"cwd");dst[n]=0;
    f=fopen(capture_path("cwd"),"wx");require(f&&fputs(dst,f)>=0&&fclose(f)==0,"save cwd");
    f=fopen(capture_path("fds"),"wx");require(f!=NULL,"fds");
    for(int i=3;i<64;i++){
        snprintf(path,sizeof(path),"/proc/%d/fd/%d",pid,i);n=readlink(path,dst,sizeof(dst)-1);if(n<0)continue;
        require(n<(ssize_t)sizeof(dst)-1,"fd path");dst[n]=0;int bytes=-1;
        if(!strncmp(dst,"pipe:[",6)){int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);if(fd>=0){if(ioctl(fd,FIONREAD,&bytes)<0)bytes=-1;close(fd);}}
        require(fprintf(f,"%d %d %s\n",i,bytes,dst)>0,"fd report");
    }
    require(fclose(f)==0,"fds close");
    struct stat st;require(stat(syms,&st)==0&&st.st_size>0,"symbol identity");
    snprintf(path,sizeof(path),"/proc/%d/exe",pid);struct stat elf;require(stat(path,&elf)==0,"exe identity");
    f=fopen(capture_path("stat"),"wx");require(f!=NULL&&fprintf(f,"%ju %ju %ju %ju %ju\n",(uintmax_t)st.st_dev,(uintmax_t)st.st_ino,(uintmax_t)st.st_size,(uintmax_t)elf.st_dev,(uintmax_t)elf.st_ino)>0&&fclose(f)==0,"stat report");
    char *last=strrchr(syms,'/');require(last!=NULL,"symbol path");*last=0;
    require(strlen(syms)+sizeof("/raw-dylibs")<=sizeof(syms),"raw name");strcat(syms,"/raw-dylibs");
    int present=stat(syms,&st)==0;require(present?S_ISDIR(st.st_mode):errno==ENOENT,"raw dylib directory");
    if(present){DIR *d=opendir(syms);require(d!=NULL,"raw dylibs");struct dirent *x;while((x=readdir(d))){require(!strcmp(x->d_name,".")||!strcmp(x->d_name,".."),"unexpected populated raw dylibs");}closedir(d);}
    f=fopen(capture_path("raw-present"),"wx");require(f&&fprintf(f,"%d\n",present)>0&&fclose(f)==0,"dir state");
}
