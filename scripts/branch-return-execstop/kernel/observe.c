#define _GNU_SOURCE
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/audit.h>
#include <openssl/evp.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

/* Source of the bounded NUL argv + descendant wait loop: the signed QA
   scripts/ohm-packed-ruff/harness/trace-compilers.c. No PMU or tracee writes. */
enum { CAP=8*1024*1024, MAX_IMAGE=4096 };
enum { NONE, CREATE, EXEC, INSTALLED };
struct task { unsigned serial, ordinal; pid_t tgid, spawned; bool known,born,exit_seen; int pending; };
struct image { struct stat st; int fd; };
static struct task *tasks;
static struct image images[MAX_IMAGE];
static unsigned image_count, serial, exec_count, births, final, replacements;
static pid_t ceiling;
static FILE *events;
static char *argv_bytes;

static void refuse(const char *message) {
    fprintf(stderr,"observer refusal: %s (errno %d)\n",message,errno);
    if (events) { fprintf(events,"REFUSE\t%s\t%d\n",message,errno); fflush(events); }
    exit(125);
}
static void need(bool test,const char *message) { if(!test) refuse(message); }
static struct task *slot(pid_t p) { need(p>0 && p<=ceiling,"kernel tid bound");return &tasks[p]; }
static struct task *get(pid_t p) {
    struct task *t=slot(p); if(!t->serial) t->serial=++serial; return t;
}
static void resume(pid_t p,int op,int sig) {
    if(ptrace(op,p,0,(void *)(intptr_t)sig)<0 && errno!=ESRCH) refuse("ptrace resume");
}
static void hex(const void *data,size_t n) {
    static const char table[]="0123456789abcdef";
    const unsigned char *s=data;
    for(size_t i=0;i<n;i++){putc_unlocked(table[s[i]>>4],events);putc_unlocked(table[s[i]&15],events);}
}
static size_t bounded_read(int fd,void *out,size_t cap) {
    size_t pos=0;
    while(pos<cap) {
        ssize_t n=read(fd,(char *)out+pos,cap-pos);
        if(n<0 && errno==EINTR) continue;
        need(n>=0,"proc read"); if(!n)break;pos+=(size_t)n;
    }
    need(pos<cap,"incomplete bounded proc payload"); return pos;
}
static int proc_open(pid_t tid,const char *file) {
    char path[80];snprintf(path,sizeof(path),"/proc/%d/%s",tid,file);
    int fd=open(path,O_RDONLY|O_CLOEXEC);need(fd>=0,path);return fd;
}
static void proc_link(pid_t tid,const char *name) {
    char key[100],out[8192]; snprintf(key,sizeof(key),"/proc/%d/%s",tid,name);
    ssize_t n=readlink(key,out,sizeof(out));need(n>0&&n<(ssize_t)sizeof(out),"unreadable proc link");hex(out,n);
}
static pid_t group_of(pid_t p) {
    int fd=proc_open(p,"status");char b[32768];size_t n=bounded_read(fd,b,sizeof(b)-1);close(fd);b[n]=0;
    char *v=strstr(b,"\nTgid:");int id=0;need(v&&sscanf(v,"\nTgid: %d",&id)==1&&id>0,"missing actual Tgid");return id;
}
static bool same(const struct stat *a,const struct stat *b) {
    return a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_size==b->st_size&&a->st_mode==b->st_mode&&
        a->st_mtim.tv_sec==b->st_mtim.tv_sec&&a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&
        a->st_ctim.tv_sec==b->st_ctim.tv_sec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
}
static unsigned image_for(pid_t p) {
    int fd=proc_open(p,"exe");struct stat st,end;need(fstat(fd,&st)==0&&S_ISREG(st.st_mode),"nonregular exec");
    for(unsigned i=0;i<image_count;i++) if(same(&images[i].st,&st)){close(fd);return i+1;}
    need(image_count<MAX_IMAGE,"too many distinct executable objects");
    Elf64_Ehdr hdr;
    need(pread(fd,&hdr,sizeof(hdr),0)==sizeof(hdr)&&memcmp(hdr.e_ident,ELFMAG,SELFMAG)==0&&
         hdr.e_ident[EI_CLASS]==ELFCLASS64&&hdr.e_ident[EI_DATA]==ELFDATA2LSB&&hdr.e_machine==EM_X86_64,
         "unsupported loaded ELF ABI");
    EVP_MD_CTX *md=EVP_MD_CTX_new();need(md&&EVP_DigestInit_ex(md,EVP_sha256(),0),"SHA init");
    unsigned char buf[65536],digest[32]; unsigned len;off_t total=0;
    for(;;){
        ssize_t n=read(fd,buf,sizeof(buf));if(n<0&&errno==EINTR)continue;
        need(n>=0,"read loaded executable");if(!n)break;
        total+=n;need(EVP_DigestUpdate(md,buf,n)==1,"SHA update");
    }
    need(EVP_DigestFinal_ex(md,digest,&len)==1&&len==sizeof(digest)&&total==st.st_size&&
         fstat(fd,&end)==0&&same(&st,&end),"unstable executable bytes");EVP_MD_CTX_free(md);
    images[image_count++]=(struct image){.st=st,.fd=fd}; /* pin identity, including an unlinked inode */
    fprintf(events,"I\t%u\t%ju\t%ju\t%jd\t%jo\t%jd.%09ld\t%jd.%09ld\t",image_count,
            (uintmax_t)st.st_dev,(uintmax_t)st.st_ino,(intmax_t)st.st_size,(uintmax_t)st.st_mode,
            (intmax_t)st.st_mtim.tv_sec,st.st_mtim.tv_nsec,(intmax_t)st.st_ctim.tv_sec,st.st_ctim.tv_nsec);
    hex(digest,len);fputc('\n',events);return image_count;
}
static void execfn(pid_t p) {
    Elf64_auxv_t aux[256];int fd=proc_open(p,"auxv");size_t n=bounded_read(fd,aux,sizeof(aux));close(fd);
    need(n&&n%sizeof(*aux)==0&&aux[n/sizeof(*aux)-1].a_type==AT_NULL,"incomplete auxv");
    uintptr_t addr=0;
    for(size_t i=0;i<n/sizeof(*aux);i++) if(aux[i].a_type==AT_EXECFN){need(!addr,"duplicate AT_EXECFN");addr=aux[i].a_un.a_val;}
    need(addr,"absent AT_EXECFN"); fd=proc_open(p,"mem");size_t pos=0;char text[8192];
    while(pos<sizeof(text)){
        size_t want=sizeof(text)-pos; if(want>256) want=256;
        ssize_t got=pread(fd,text+pos,want,(off_t)(addr+pos));
        if(got<0&&errno==EINTR)continue;
        need(got>0,"read kernel AT_EXECFN");
        char *nul=memchr(text+pos,0,got);if(nul){hex(text,(size_t)(nul-text));close(fd);return;}pos+=got;
    }
    refuse("truncated AT_EXECFN");
}
static void exec_image(pid_t p,unsigned long old) {
    struct task *t=slot((pid_t)old),*current=slot(p);
    need(t->known&&t->born&&t->pending==EXEC&&t->tgid==p,"unknown executing thread or syscall ABI");
    if(old!=(unsigned long)p){
        if(current->serial){
            need(current->tgid==p&&current->exit_seen&&!current->pending,"displaced leader without kernel EXIT");
            fprintf(events,"D\t%u\t%d\t%u\n",current->serial,p,t->serial);replacements++;
        }
        *current=*t; memset(t,0,sizeof(*t)); t=current;
    }
    t->pending=INSTALLED; t->ordinal=++exec_count; unsigned img=image_for(p);
    int fd=proc_open(p,"cmdline");size_t n=bounded_read(fd,argv_bytes,CAP);close(fd);
    need(n&&argv_bytes[n-1]==0,"incomplete installed argv");
    fprintf(events,"E\t%u\t%u\t%d\t%lu\t%u\t",t->ordinal,t->serial,p,old,img);
    proc_link(p,"exe");fputc('\t',events);proc_link(p,"cwd");fputc('\t',events);
    execfn(p);fputc('\t',events);hex(argv_bytes,n);fputc('\n',events);
}
static unsigned long message(pid_t p) {
    unsigned long val;need(ptrace(PTRACE_GETEVENTMSG,p,0,&val)==0,"ptrace event payload");return val;
}
static void syscall_stop(pid_t p,struct task *t) {
    struct __ptrace_syscall_info info;
    long bytes=ptrace(PTRACE_GET_SYSCALL_INFO,p,sizeof(info),&info);
    need(bytes>=0&&info.arch==AUDIT_ARCH_X86_64,"unsupported syscall ABI");
    if(info.op==PTRACE_SYSCALL_INFO_ENTRY){
        uint64_t n=info.entry.nr;
        need(!(n&0x40000000) || n==(uint64_t)-1,"x32 syscall ABI");
        need(!t->pending,"previous observed syscall did not close");
        if(n==SYS_fork||n==SYS_vfork||n==SYS_clone||n==SYS_clone3){
            /* Successful returns must match an actual ptrace child event. A denied/unsupported
               clone3 may still legitimately fail without any event. */
            if(n==SYS_clone) need(!(info.entry.args[0]&CLONE_UNTRACED),"CLONE_UNTRACED escape");
            if(n==SYS_clone3&&info.entry.args[1]>=sizeof(uint64_t)){
                uint64_t flags=0;struct iovec here={&flags,sizeof(flags)},there={(void *)(uintptr_t)info.entry.args[0],sizeof(flags)};
                ssize_t got=process_vm_readv(p,&here,1,&there,1,0);
                if(got==(ssize_t)sizeof(flags)) need(!(flags&CLONE_UNTRACED),"clone3 CLONE_UNTRACED escape");
            }
            t->pending=CREATE;t->spawned=0;
        } else if(n==SYS_execve||n==SYS_execveat){t->pending=EXEC;}
    } else if(info.op==PTRACE_SYSCALL_INFO_EXIT){
        if(t->pending==CREATE){
            if(info.exit.is_error)need(!t->spawned,"kernel child event with failed create");
            else need(t->spawned>0&&info.exit.rval==t->spawned,"positive process creation without matching child event");
            fprintf(events,"C\t%u\t%d\t%lld\t%d\n",t->serial,p,(long long)info.exit.rval,t->spawned);
        } else if(t->pending==INSTALLED){
            need(!info.exit.is_error&&info.exit.rval==0,"committed exec did not return zero");
            fprintf(events,"P\t%u\t%d\t%u\n",t->serial,p,t->ordinal);
        } else if(t->pending==EXEC){
            need(info.exit.is_error,"zero exec return without committed kernel image");
            fprintf(events,"F\t%u\t%d\t%lld\n",t->serial,p,(long long)info.exit.rval);
        }
        t->pending=NONE;
    } else refuse("unknown syscall-stop direction");
}
int main(int argc,char **argv) {
    if(argc<4||strcmp(argv[2],"--")){fprintf(stderr,"usage: observe NEW_LEDGER -- COMMAND [ARGS]\n");return 125;}
    int logfd=open(argv[1],O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600);
    need(logfd>=0,"new private ledger");events=fdopen(logfd,"w");need(events!=NULL,"private ledger stream");
    FILE *lim=fopen("/proc/sys/kernel/pid_max","re");need(lim&&fscanf(lim,"%d",&ceiling)==1&&ceiling>1&&ceiling<=4194304,"pid bound");fclose(lim);
    tasks=calloc((size_t)ceiling+1,sizeof(*tasks));argv_bytes=malloc(CAP);need(tasks&&argv_bytes,"alloc");
    int gate[2];need(pipe2(gate,O_CLOEXEC)==0,"pipe");
    pid_t root=fork();need(root>=0,"fork root");
    if(!root){close(gate[1]);char c;ssize_t r;do{r=read(gate[0],&c,1);}while(r<0&&errno==EINTR);
        close(gate[0]);if(r!=1) _exit(125);execvp(argv[3],argv+3);_exit(126);}
    close(gate[0]);
    unsigned opts=PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE|
                  PTRACE_O_TRACEEXIT|PTRACE_O_TRACESYSGOOD|PTRACE_O_EXITKILL;
    need(ptrace(PTRACE_SEIZE,root,0,opts)==0&&ptrace(PTRACE_INTERRUPT,root,0,0)==0,"seize own gated child");
    int st;need(waitpid(root,&st,__WALL)==root&&WIFSTOPPED(st)&&(unsigned)st>>16==PTRACE_EVENT_STOP,"initial stop");
    struct task *rt=get(root);rt->known=rt->born=true;rt->tgid=root;
    fprintf(events,"R\t%u\t%d\n",rt->serial,root);need(write(gate[1],"x",1)==1,"release child");close(gate[1]);resume(root,PTRACE_SYSCALL,0);
    int root_code=-1;
    for(;;){
        pid_t p=waitpid(-1,&st,__WALL);
        if(p<0&&errno==EINTR)continue;
        if(p<0&&errno==ECHILD)break;
        need(p>0,"wait");
        struct task *t=WIFSTOPPED(st)&&((unsigned)st>>16)==PTRACE_EVENT_EXEC?slot(p):get(p);
        if(WIFEXITED(st)||WIFSIGNALED(st)){
            need(t->known&&t->born&&t->exit_seen&&!t->pending,"unclosed final task");
            fprintf(events,"T\t%u\t%d\t%d\n",t->serial,p,st);final++;
            if(p==root)root_code=WIFEXITED(st)?WEXITSTATUS(st):128+WTERMSIG(st);
            memset(t,0,sizeof(*t));continue;
        }
        need(WIFSTOPPED(st),"unknown stop");int sig=WSTOPSIG(st);unsigned ev=(unsigned)st>>16;
        if(ev==PTRACE_EVENT_STOP){
            if(!t->born){
                need(sig==SIGTRAP,"unexpected initial child stop");t->born=true;t->tgid=group_of(p);
                fprintf(events,"B\t%u\t%d\t%d\n",t->serial,p,t->tgid);births++;
                if(!t->known)continue; /* stop-before-parent notification; do not release early */
            }else if(sig==SIGSTOP||sig==SIGTSTP||sig==SIGTTIN||sig==SIGTTOU){resume(p,PTRACE_LISTEN,0);continue;}
            else need(sig==SIGTRAP,"unexpected seized group stop");
        }else if(ev==PTRACE_EVENT_EXEC){exec_image(p,message(p));}
        else if(ev==PTRACE_EVENT_FORK||ev==PTRACE_EVENT_VFORK||ev==PTRACE_EVENT_CLONE){
            pid_t ch=(pid_t)message(p);struct task *c=get(ch);
            need(t->pending==CREATE&&t->known&&!t->spawned&&!c->known,"unexpected fork ancestry");
            c->known=true;t->spawned=ch;fprintf(events,"N\t%u\t%d\t%u\t%u\t%d\n",t->serial,p,ev,c->serial,ch);
            if(c->born)resume(ch,PTRACE_SYSCALL,0);
        }else if(ev==PTRACE_EVENT_EXIT){
            need(!t->exit_seen&&(t->pending!=CREATE||t->spawned>0),"interrupted unresolved child creation");
            if(t->pending==CREATE)fprintf(events,"Y\t%u\t%d\t%d\n",t->serial,p,t->spawned);
            unsigned long raw=message(p);
            if(t->pending==INSTALLED)fprintf(events,"L\t%u\t%d\t%u\n",t->serial,p,t->ordinal);
            if(t->pending==EXEC)fprintf(events,"A\t%u\t%d\t%lu\n",t->serial,p,raw);
            t->pending=NONE;t->exit_seen=true;fprintf(events,"X\t%u\t%d\t%lu\n",t->serial,p,raw);
        }else if(!ev&&sig==(SIGTRAP|0x80)){syscall_stop(p,t);}
        else{need(!ev,"unexpected ptrace event");resume(p,PTRACE_SYSCALL,sig);continue;}
        resume(p,PTRACE_SYSCALL,0);
    }
    need(root_code>=0&&exec_count>0&&serial==births+1&&serial==final+replacements,"incomplete family closure");
    fprintf(events,"OK\t%d\t%u\t%u\t%u\t%u\t%u\n",root_code,exec_count,serial,births,final,replacements);
    need(!ferror(events)&&fclose(events)==0,"ledger flush");return root_code;
}
