#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
#define CHECK(e) do{if(!(e)){perror(#e);_exit(92);}}while(0)
static void wait_code(pid_t c,int n){int s;CHECK(c>0&&waitpid(c,&s,0)==c&&WIFEXITED(s)&&WEXITSTATUS(s)==n);}
static void *thread_exec(void *p){(void)p;execl("/bin/sh","nonleader-chosen-argv0","-c","exit 37",NULL);_exit(91);}
static void passfd(int sock,int *fd,int sendit){
    char c='x',control[CMSG_SPACE(sizeof(int))]={0};
    struct iovec vec={&c,1};struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1,.msg_control=control,.msg_controllen=sizeof(control)};
    if(sendit){struct cmsghdr *h=CMSG_FIRSTHDR(&msg);h->cmsg_level=SOL_SOCKET;h->cmsg_type=SCM_RIGHTS;h->cmsg_len=CMSG_LEN(sizeof(int));memcpy(CMSG_DATA(h),fd,sizeof(int));CHECK(sendmsg(sock,&msg,0)==1);}
    else{CHECK(recvmsg(sock,&msg,0)==1);struct cmsghdr *h=CMSG_FIRSTHDR(&msg);CHECK(h&&h->cmsg_level==SOL_SOCKET&&h->cmsg_type==SCM_RIGHTS);memcpy(fd,CMSG_DATA(h),sizeof(int));}
}
static void aborted_opaque(void){
    int pair[2];CHECK(socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,pair)==0);
    pid_t c=fork();CHECK(c>=0);
    if(!c){
        close(pair[0]);struct sock_filter f[]={
            BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
            BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_execve,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_USER_NOTIF),
            BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};
        struct sock_fprog prog={.len=sizeof(f)/sizeof(*f),.filter=f};
        CHECK(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)==0);
        int fd=syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_NEW_LISTENER,&prog);CHECK(fd>=0);
        passfd(pair[1],&fd,1);close(fd);close(pair[1]);
        (void)syscall(SYS_execve,(void *)1,(void *)2,(void *)3);_exit(91);
    }
    close(pair[1]);int fd=-1;passfd(pair[0],&fd,0);close(pair[0]);
    struct seccomp_notif n={0};CHECK(ioctl(fd,SECCOMP_IOCTL_NOTIF_RECV,&n)==0);
    CHECK(n.pid==(uint32_t)c&&n.data.nr==SYS_execve&&n.data.args[0]==1&&n.data.args[1]==2&&n.data.args[2]==3);
    CHECK(ioctl(fd,SECCOMP_IOCTL_NOTIF_ID_VALID,&n.id)==0);
    printf("opaque kernel notification pid=%d pointers=1,2,3\n",c);fflush(stdout);
    CHECK(kill(c,SIGKILL)==0);int s;CHECK(waitpid(c,&s,0)==c&&WIFSIGNALED(s)&&WTERMSIG(s)==SIGKILL);close(fd);
}
int main(int argc,char **argv){
    CHECK(argc>=2);
    if(!strcmp(argv[1],"escape")||!strcmp(argv[1],"escape3")){
        struct clone_args a={.flags=CLONE_UNTRACED,.exit_signal=SIGCHLD};
        pid_t c=!strcmp(argv[1],"escape")?syscall(SYS_clone,CLONE_UNTRACED|SIGCHLD,0,0,0,0):syscall(SYS_clone3,&a,sizeof(a));
        if(!c){execl("/usr/bin/true","untraced",NULL);_exit(91);} if(c>0)wait_code(c,0);return 77;
    }
    if(!strcmp(argv[1],"thread")){pthread_t t;CHECK(!pthread_create(&t,NULL,thread_exec,NULL));for(;;)pause();}
    if(!strcmp(argv[1],"duplicate")){
        const char *s=getenv("REEXEC_N");int n=s?atoi(s):0;
        if(n==2)return 19;
        char value[32];snprintf(value,sizeof(value),"%d",n+1);CHECK(setenv("REEXEC_N",value,1)==0);
        execv("/proc/self/exe",argv);_exit(91);
    }
    if(!strcmp(argv[1],"abort")){aborted_opaque();return 13;}
    if(!strcmp(argv[1],"signals")){
        pid_t c=fork();CHECK(c>=0);if(!c){raise(SIGSTOP);_exit(12);}
        int s;CHECK(waitpid(c,&s,WUNTRACED)==c&&WIFSTOPPED(s)&&WSTOPSIG(s)==SIGSTOP);
        CHECK(kill(c,SIGCONT)==0);wait_code(c,12);return 14;
    }
    CHECK(!strcmp(argv[1],"family")&&argc==3);
    const char *nonutf="byte-\xff";
    char *vec[]={"identical argv0","x","x","",(char *)nonutf,NULL};
    for(int i=0;i<2;i++){pid_t c=fork();CHECK(c>=0);if(!c){execve("/usr/bin/true",vec,environ);_exit(91);}wait_code(c,0);}
    pid_t c=vfork();CHECK(c>=0);if(!c){execve("/usr/bin/true",vec,environ);_exit(91);}wait_code(c,0);
    c=fork();CHECK(c>=0);
    if(!c){pid_t c2=fork();CHECK(c2>=0);if(!c2){int fd=open("/usr/bin/true",O_RDONLY|O_CLOEXEC);CHECK(fd>=0);
        syscall(SYS_execveat,fd,"",vec,environ,AT_EMPTY_PATH);_exit(91);}wait_code(c2,0);_exit(11);}wait_code(c,11);
    c=fork();CHECK(c>=0);if(!c){execl(argv[2],"unrelated-script-argv0","script-argument",NULL);_exit(91);}wait_code(c,7);
    CHECK(syscall(SYS_execve,(void *)1,(void *)2,(void *)3)==-1&&errno==EFAULT);
    CHECK(syscall(SYS_execve,"/no-such-ohm-executable",vec,environ)==-1&&errno==ENOENT);
    return 23;
}
