#include <errno.h>
#include <err.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <unistd.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <sys/wait.h>

int main(int argc, char **argv) {
    if (argc<3) errx(2,"meter RECEIPT COMMAND...");
    int pipes[2];
    if (pipe(pipes)<0) err(2,"pipe");
    pid_t child=fork();
    if (child<0) err(2,"fork");
    if (!child) {
        char go;
        close(pipes[1]);
        if (read(pipes[0],&go,1)!=1) _exit(127);
        close(pipes[0]);
        execvp(argv[2],argv+2);
        err(127,"%s",argv[2]);
    }
    close(pipes[0]);
    struct perf_event_attr attr={
        .size=sizeof(attr), .type=PERF_TYPE_HARDWARE, .config=PERF_COUNT_HW_INSTRUCTIONS,
        .inherit=1, .exclude_kernel=1, .exclude_hv=1, .disabled=1, .enable_on_exec=1,
        .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING
    };
    int fd=syscall(SYS_perf_event_open,&attr,child,-1,-1,0);
    if (fd<0) err(2,"open instructions event");
    if (write(pipes[1],"1",1)!=1) err(2,"release");
    close(pipes[1]);
    int status;
    while (waitpid(child,&status,0)<0)
        if (errno!=EINTR) err(2,"wait");
    uint64_t values[3];
    if (read(fd,&values,sizeof(values))!=sizeof(values)) err(2,"read");
    close(fd);
    if (!values[0] || !values[2]) err(2,"no count");
    FILE *out=fopen(argv[1],"wx");
    if (!out) err(2,"open receipt");
    fprintf(out,"%"PRIu64" %"PRIu64" %"PRIu64"\n",values[0],values[1],values[2]);
    if (ferror(out)||fclose(out))err(2,"close");
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}

