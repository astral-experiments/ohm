#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void *work(void *n) {
    volatile uint64_t value=9;
    for (uintptr_t i=0;i<(uintptr_t)n;i++) value=3*value+i;
    return NULL;
}
int main(int argc,char **argv) {
    if(argc!=3) return 2;
    uintptr_t n=strtoul(argv[1],0,10);
    if(!n || n>16000000) return 3;
    pthread_t worker;
    if(pthread_create(&worker,0,work,(void *)n))return 4;
    work((void *)n);
    if(pthread_join(worker,0))return 5;
    if(!strcmp(argv[2],"spawn")){
        pid_t child=fork();
        if(child<0)return 6;
        if(!child){execl(argv[0],argv[0],"8000000","child",(char *)NULL);_exit(7);}
        int status;
        if(waitpid(child,&status,0)!=child || status)return 8;
    }
    return 0;
}
