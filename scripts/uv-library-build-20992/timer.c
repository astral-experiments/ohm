#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
static long long now(void) { struct timespec t; if (clock_gettime(CLOCK_MONOTONIC, &t)) abort(); return (long long)t.tv_sec*1000000000+t.tv_nsec; }
int main(int argc,char **argv) {
    if(argc!=2) return 2;
    long milliseconds=strtol(argv[1], NULL, 10);
    if(milliseconds<1 || milliseconds>100) return 2;
    struct timespec req={.tv_sec=0,.tv_nsec=milliseconds*1000000};
    long long start=now();
    while(nanosleep(&req,&req)!=0) if(errno!=EINTR) return 3;
    printf("%lld\n",now()-start); return 0;
}

