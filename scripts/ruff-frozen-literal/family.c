/* A deterministic charge in two other threads and a separately exec'd child. */
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static uint64_t burn(uint64_t n){volatile uint64_t x=7;for(uint64_t j=0;j<n;j++)x=x*33+9;return x;}
static void *worker(void *ptr){uint64_t*n=ptr;*n=burn(*n);return NULL;}
int main(int argc,char **argv){
    if(argc<3)return 2;
    uint64_t n=strtoull(argv[2],NULL,10);
    if(strcmp(argv[1],"sub")==0){printf("child %" PRIu64 "\n",burn(3*n));return 0;}
    pid_t kid=fork();if(kid<0)return 3;
    if(!kid){execl(argv[0],argv[0],"sub",argv[2],(char*)NULL);_exit(3);}
    uint64_t a=n,b=2*n;pthread_t t,u;
    if(pthread_create(&t,NULL,worker,&a) || pthread_create(&u,NULL,worker,&b))return 4;
    int s;if(pthread_join(t,NULL)||pthread_join(u,NULL)||waitpid(kid,&s,0)!=kid||s)return 5;
    printf("parent %" PRIu64 " %" PRIu64 "\n",a,b);return 0;
}
