"""Charge the live coordinator separately from the unmodified Cargo process tree."""
import ctypes,os,subprocess
LIB=None
C=r'''
#define _GNU_SOURCE
#include <errno.h>
#include <linux/perf_event.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
int own_counter(void) {
    struct perf_event_attr a={.type=PERF_TYPE_HARDWARE,.size=sizeof(a),.config=PERF_COUNT_HW_INSTRUCTIONS,
      .exclude_kernel=1,.exclude_hv=1,.pinned=1,.inherit=0,
      .read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING};
    return (int)syscall(__NR_perf_event_open,&a,0,-1,-1,PERF_FLAG_FD_CLOEXEC);
}
int stop_counter(int fd,uint64_t out[3]) {
    int ok=ioctl(fd,PERF_EVENT_IOC_DISABLE,0)==0 && read(fd,out,3*sizeof(*out))==(ssize_t)(3*sizeof(*out));
    return close(fd)==0 && ok ? 0 : -1;
}
'''
def prepare(root,clock):
    global LIB
    cc=root/'qa-coordinator-counter.c';so=root/'qa-coordinator-counter.so';cc.write_text(C)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2','-fPIC','-shared',cc,'-o',so],check=True)
    LIB=ctypes.CDLL(str(so),use_errno=True);LIB.own_counter.argtypes=[];LIB.own_counter.restype=ctypes.c_int
    LIB.stop_counter.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint64)];LIB.stop_counter.restype=ctypes.c_int
    t=clock.read_text();p='    if(write(gate[1],"g",1)!=1)return 125;';q='    uint64_t v[3];';end='    return WIFEXITED(status)'
    assert all(t.count(x)==1 for x in (p,q,end,'#include <unistd.h>'))
    t=t.replace('#include <unistd.h>','#include <unistd.h>\n#include <time.h>\n#include <limits.h>')
    t=t.replace(p,'    struct timespec a0,a1; if(clock_gettime(CLOCK_MONOTONIC_RAW,&a0))return 125;\n'+p)
    t=t.replace(q,'    if(clock_gettime(CLOCK_MONOTONIC_RAW,&a1))return 125;\n'+q)
    t=t.replace(end,'''    char filename[PATH_MAX]; int count=snprintf(filename,sizeof(filename),"%s.elapsed-ns",argv[1]);
    if(count<=0 || (size_t)count>=sizeof(filename))return 125;
    FILE *actual=fopen(filename,"wx");if(!actual)return 125;
    uint64_t ns=(uint64_t)(a1.tv_sec-a0.tv_sec)*1000000000u+a1.tv_nsec-a0.tv_nsec;
    fprintf(actual,"%" PRIu64 "\\n",ns);if(fclose(actual))return 125;
'''+end)
    stage=root/'qa-whole-output-clock.c';stage.write_text(t)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2',stage,'-o',root/'whole_count'],check=True)
def start():
    fd=LIB.own_counter()
    if fd<0:raise OSError(ctypes.get_errno(),'coordinator thread retired instructions')
    return fd
def end(fd):
    row=(ctypes.c_uint64*3)();assert LIB.stop_counter(fd,row)==0
    n,enabled,running=row;assert n>0 and enabled>=running>0 and running>=.98*enabled,(n,enabled,running)
    return {'instructions':n,'enabled':enabled,'running':running}
def calibrate():
    rows=[]
    for n in (40000,160000):
        fd=start();v=0
        for i in range(n):v=(v+i)&65535
        rows.append([n,v,end(fd)])
    assert 3.5<rows[1][2]['instructions']/rows[0][2]['instructions']<4.5
    return rows
