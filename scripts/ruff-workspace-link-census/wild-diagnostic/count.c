#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Hardware instructions for one genuine exec and its threads. The launcher and observer are outside. */
int main(int argc,char **argv) {
    if (argc < 4) return 125;
    int gate[2]; if (pipe2(gate,O_CLOEXEC)) return 125;
    pid_t pid=fork();
    if (pid<0) return 125;
    if (pid==0) {
        char go; close(gate[1]); if (read(gate[0],&go,1)!=1) _exit(125);
        close(gate[0]); execv(argv[2],argv+3); _exit(127);
    }
    close(gate[0]);
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,
        .disabled=1,.inherit=1,.exclude_kernel=1,.exclude_hv=1,.enable_on_exec=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    int fd=syscall(__NR_perf_event_open,&a,pid,-1,-1,PERF_FLAG_FD_CLOEXEC);
    if (fd<0) {int e=errno; close(gate[1]);waitpid(pid,NULL,0);fprintf(stderr,"perf_event_open: %s\n",strerror(e));return 126;}
    if(write(gate[1],"g",1)!=1)return 125;
    close(gate[1]);
    int status=0;while(waitpid(pid,&status,0)<0){if(errno!=EINTR)return 125;}
    uint64_t v[3];if(read(fd,v,sizeof(v))!=sizeof(v))return 125;close(fd);
    FILE *f=fopen(argv[1],"wx");if(!f)return 125;
    fprintf(f,"{\"pid\":%d,\"instructions\":%" PRIu64 ",\"enabled\":%" PRIu64 ",\"running\":%" PRIu64 ",\"status\":%d}\n",pid,v[0],v[1],v[2],status);
    if(fclose(f))return 125;
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
