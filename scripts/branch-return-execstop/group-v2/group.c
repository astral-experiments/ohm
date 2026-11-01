#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <linux/futex.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Positive kernel events are measured by the external observer. Emit a separate
   ground-truth process inventory and ensure the final parent sees the status. */
enum { THREADS = 8 };
static atomic_uint ready;
static atomic_uint go;
static int peers_exit;
static void *work(void *unused) {
    (void)unused;
    dprintf(1, "worker %ld group %d\n", syscall(SYS_gettid), getpid());
    atomic_fetch_add(&ready, 1);
    while(!atomic_load(&go)) syscall(SYS_futex,&go,FUTEX_WAIT_PRIVATE,0,NULL,NULL,0);
    if(peers_exit)syscall(SYS_exit,37);
    for (;;) syscall(SYS_gettid);
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 2) return 61;
    if (!strcmp(argv[1],"--installed")) {
        pthread_t threads[THREADS];
        for(int i=0;i<THREADS;i++)if(pthread_create(&threads[i],NULL,work,NULL))return 64;
        while(atomic_load(&ready)<THREADS)sched_yield();
        syscall(SYS_exit_group,37);
        return 68;
    }
    int cycles = atoi(argv[1]);
    peers_exit=getenv("FIXTURE_RACING_THREAD_EXIT")!=NULL;
    if (cycles < 1 || cycles > 128) return 62;
    for (int i=0;i<cycles;i++) {
        pid_t pid=fork();
        if(pid<0)return 63;
        if(!pid) {
            pthread_t th[THREADS];
            for(int j=0;j<THREADS;j++)if(pthread_create(&th[j],NULL,work,NULL))_exit(64);
            while(atomic_load(&ready)<THREADS) sched_yield();
            /* Real unrelated exec before group shutdown accounts for every cycle. */
            pid_t child=fork();
            if(child<0)_exit(65);
            if(!child){execl("/usr/bin/true","exactly-once",NULL);_exit(66);}
            int status;
            if(waitpid(child,&status,0)!=child||status!=0)_exit(67);
            dprintf(1,"exiting %d after exec %d\n",getpid(),child);
            atomic_store(&go,1);
            syscall(SYS_futex,&go,FUTEX_WAKE_PRIVATE,INT_MAX,NULL,NULL,0);
            syscall(SYS_exit_group,37);
            _exit(68);
        }
        int status;
        if(waitpid(pid,&status,0)!=pid || !WIFEXITED(status) || WEXITSTATUS(status)!=37)return 69;
    }
    return 0;
}
