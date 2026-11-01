#define _GNU_SOURCE
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static int announce[2];
static void *attempt(void *unused) {
    (void)unused;
    struct sock_filter insn[]={
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_execve,0,1),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)
    };
    struct sock_fprog pr={4,insn};
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)) _exit(60);
    int fd=syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_NEW_LISTENER,&pr);
    if(fd<0||write(announce[1],&fd,sizeof fd)!=sizeof fd) _exit(61);
    syscall(SYS_execve,(void*)1,(void*)2,(void*)3);_exit(62);
}
int main(void) {
    pid_t child=fork();if(child<0)return 63;
    if(!child) {
        pthread_t t;int fd;
        if(pipe(announce)||pthread_create(&t,NULL,attempt,NULL)||read(announce[0],&fd,sizeof fd)!=sizeof fd)_exit(64);
        struct seccomp_notif n={0};
        if(ioctl(fd,SECCOMP_IOCTL_NOTIF_RECV,&n)||n.data.nr!=SYS_execve||
           n.data.args[0]!=1||ioctl(fd,SECCOMP_IOCTL_NOTIF_ID_VALID,&n.id))_exit(65);
        dprintf(1,"pending exec tid=%u group=%d\n",n.pid,getpid());
        syscall(SYS_exit_group,37);_exit(66);
    }
    int status;
    return waitpid(child,&status,0)==child && WIFEXITED(status)&&WEXITSTATUS(status)==37?0:67;
}
