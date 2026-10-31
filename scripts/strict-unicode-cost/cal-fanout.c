#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Four separately identified sibling roots and one outside loop. */
int main(int argc,char **argv){
    if(argc!=4)return 101;
    const char *names[]={"build_rustc","generator","unicode_rustc","ron"};
    const char *depth[]={"2","0","thread","exec"};
    const char *copies[]={"2","1","2","1"};
    const int m[]={1,3,4,5,7};
    pid_t p[5];long n=strtol(argv[3],NULL,10);
    for(int i=0;i<5;i++){
        p[i]=fork();if(p[i]<0)return 102;
        if(!p[i]){
            char it[48],path[PATH_MAX];snprintf(it,sizeof(it),"%ld",n*m[i]);
            if(i==4){execl(argv[2],argv[2],"0",it,"1",(char*)0);_exit(103);}
            if(snprintf(path,sizeof(path),"%s/%s",argv[1],names[i])>=(int)sizeof(path))_exit(104);
            execl(path,path,"selected",argv[2],depth[i],it,copies[i],(char*)0);_exit(105);
        }
    }
    for(int i=0;i<5;i++){int s;if(waitpid(p[i],&s,0)!=p[i]||!WIFEXITED(s)||WEXITSTATUS(s)!=0)return 106;}
    return 0;
}
