#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/perf_event.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Count the entire exec tree including late native children. Each reaped child's kernel
   usage includes children that child has already waited for. Adopt and charge the rest. */
static const char *keys[]={"rchar","wchar","syscr","syscw","read_bytes","write_bytes","cancelled_write_bytes"};
static int read_io(pid_t pid,uint64_t *totals){
    char path[64],name[48];uint64_t v;unsigned seen=0;
    snprintf(path,sizeof(path),"/proc/%d/io",(int)pid);
    FILE *f=fopen(path,"re");if(!f){perror(path);return -1;}
    while(fscanf(f," %47[^:]: %" SCNu64,name,&v)==2){
        unsigned i;for(i=0;i<7 && strcmp(keys[i],name);i++){}
        if(i==7 || (seen&(1u<<i))){fclose(f);return -1;}
        seen|=1u<<i;totals[i]+=v;
    }
    if(seen!=127)fprintf(stderr,"incomplete %s, field mask %u, errno %d\n",path,seen,errno);
    return fclose(f)||seen!=127?-1:0;
}
static uint64_t now_ns(void){
    struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))abort();
    return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
}
static uint64_t us(struct timeval t){return (uint64_t)t.tv_sec*1000000+t.tv_usec;}
struct report {uint64_t io[7];unsigned reaped;int status;};
static int manage(int argc,char **argv,int notify) {
    (void)argc;
    if(prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0))return 125;
    pid_t root=fork();if(root<0)return 125;
    if(!root){close(notify);execv(argv[2],argv+3);_exit(127);}
    struct report rep={.status=-1};
    for(;;){
        int st;pid_t p=waitpid(-1,&st,0);
        if(p<0){if(errno==EINTR)continue;if(errno==ECHILD)break;return 125;}
        if(p==root)rep.status=st;
        rep.reaped++;
    }
    if(rep.status<0 || !rep.reaped || read_io(getpid(),rep.io))return 125;
    if(write(notify,&rep,sizeof(rep))!=sizeof(rep))return 125;
    close(notify);
    return WIFEXITED(rep.status)?WEXITSTATUS(rep.status):128+WTERMSIG(rep.status);
}
int main(int argc,char **argv){
    if(argc<4)return 125;
    int gate[2],out[2];if(pipe2(gate,O_CLOEXEC)||pipe2(out,O_CLOEXEC))return 125;
    pid_t root=fork();if(root<0)return 125;
    if(!root){
        close(gate[1]); close(out[0]); char b;if(read(gate[0],&b,1)!=1)_exit(125);
        close(gate[0]); _exit(manage(argc,argv,out[1]));
    }
    close(gate[0]);close(out[1]);uint64_t clock_values[3]={0};
#ifndef LOCAL_IO_FIXTURE_ONLY
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),
       .config=PERF_COUNT_HW_INSTRUCTIONS,.disabled=1,.inherit=1,.exclude_kernel=1,
       .exclude_hv=1,.read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    int perf=syscall(__NR_perf_event_open,&a,root,-1,-1,PERF_FLAG_FD_CLOEXEC);
    if(perf<0){int e=errno;close(gate[1]);waitpid(root,NULL,0);fprintf(stderr,"perf_event_open: %s\n",strerror(e));return 126;}
    if(ioctl(perf,PERF_EVENT_IOC_ENABLE,0)<0)return 125;
#endif
    uint64_t begin=now_ns();
    if(write(gate[1],"g",1)!=1)return 125;
    close(gate[1]);
    struct rusage usage;int ms;pid_t done;
    do {done=wait4(root,&ms,0,&usage);} while(done<0 && errno==EINTR);
    if(done!=root)return 125;
    uint64_t end=now_ns();
    struct report rep={0};if(read(out[0],&rep,sizeof(rep))!=sizeof(rep))return 125;
    close(out[0]);
    int status=rep.status;unsigned reaped=rep.reaped;uint64_t *io=rep.io;
    if(!WIFEXITED(ms)||WEXITSTATUS(ms)!=(WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status)))return 125;
    uint64_t ut=us(usage.ru_utime),st=us(usage.ru_stime),ib=usage.ru_inblock,ob=usage.ru_oublock;
    uint64_t minf=usage.ru_minflt,majf=usage.ru_majflt,nv=usage.ru_nvcsw,ni=usage.ru_nivcsw,rss=usage.ru_maxrss;
#ifndef LOCAL_IO_FIXTURE_ONLY
    if(read(perf,clock_values,sizeof(clock_values))!=sizeof(clock_values))return 125;
    close(perf);
#endif
    FILE *f=fopen(argv[1],"wx");if(!f)return 125;
    fprintf(f,"{\"pid\":%d,\"status\":%d,\"reaped\":%u,\"instructions\":%" PRIu64 ",\"enabled\":%" PRIu64 ",\"running\":%" PRIu64 ",\"elapsed_ns\":%" PRIu64 ",\"user_us\":%" PRIu64 ",\"system_us\":%" PRIu64 ",\"inblock\":%" PRIu64 ",\"outblock\":%" PRIu64 ",\"minflt\":%" PRIu64 ",\"majflt\":%" PRIu64 ",\"voluntary_switches\":%" PRIu64 ",\"involuntary_switches\":%" PRIu64 ",\"maxrss_kib\":%" PRIu64,(int)root,status,reaped,clock_values[0],clock_values[1],clock_values[2],end-begin,ut,st,ib,ob,minf,majf,nv,ni,rss);
    for(unsigned i=0;i<7;i++)fprintf(f,",\"%s\":%" PRIu64,keys[i],io[i]);
    fputs("}\n",f);if(fclose(f))return 125;
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
