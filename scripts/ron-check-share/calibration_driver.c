#define _GNU_SOURCE
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static volatile sig_atomic_t signal_seen;
static void note(int sig){signal_seen=sig;}
static int wait_ok(pid_t child) { int s;return child>0 && waitpid(child,&s,0)==child && WIFEXITED(s) && WEXITSTATUS(s)==0; }
int main(int argc,char **argv) {
    if(argc==8 && !strcmp(argv[1],"outer")) {
        // Run a sibling loop outside the selected process tree. Its deliberate
        // instructions must appear in the whole count and never in the subset.
        pid_t outside=fork();if(!outside){execl(argv[3],argv[3],"0",argv[7],"1",(char*)0);_exit(102);}
        pid_t selected=fork();if(!selected){execl(argv[2],argv[2],"selected",argv[3],argv[4],argv[5],argv[6],(char*)0);_exit(103);}
        return !(wait_ok(outside) && wait_ok(selected));
    }
    if(argc==6 && !strcmp(argv[1],"selected")) {
        struct sigaction a={.sa_handler=note};if(sigaction(SIGUSR1,&a,0)||raise(SIGUSR1)||signal_seen!=SIGUSR1)return 104;
        execl(argv[2],argv[2],argv[3],argv[4],argv[5],(char*)0);return 105;
    }
    return 101;
}
