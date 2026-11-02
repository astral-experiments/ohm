#include <pthread.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static void *loops(void *unused) {
    unsigned n=2000000; __asm__ volatile ("1: subl $1,%0\n\tjne 1b":"+r"(n)::"cc");return unused;
}
int main(int argc,char **argv) {
    if(argc<2 || !strcmp(argv[1],"empty"))return 0;
    if(!strcmp(argv[1],"loop")){loops(0);return 0;}
    if(!strcmp(argv[1],"thread")){pthread_t t;if(pthread_create(&t,0,loops,0))return 1;return pthread_join(t,0);}
    if(!strcmp(argv[1],"fork")){pid_t p=fork();if(p<0)return 1;if(!p){loops(0);_exit(0);}int s;return waitpid(p,&s,0)<0||s;}
    return 1;
}
