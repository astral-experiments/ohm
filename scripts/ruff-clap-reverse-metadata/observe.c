#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define REC "_RNvMsi_NtNtNtCsd9ZaGPDkAU_14rustc_metadata5rmeta7encoder17public_api_hasherNtB5_24ReachabilityGraphBuilder6record"
#define ADD "_RNvMsj_NtNtNtCsd9ZaGPDkAU_14rustc_metadata5rmeta7encoder17public_api_hasherNtB5_23ReachabilityGraphHashes13add_node_hash"
#define BUILD "_RNvNtNtNtCsd9ZaGPDkAU_14rustc_metadata5rmeta7encoder17public_api_hasher19build_public_hashes"
static uintptr_t base;
static FILE *regs,*payloads,*graph;
static pid_t writer;
static int target;
static void require(int ok){if(!ok){fputs("declined signed graph capture\n",stderr);_exit(91);}}
static int in_target(void){
 if(target)return target==1;
 target=2;
 const char *rustc=getenv("OHM_GRAPH_RUSTC");struct stat a,b;
 if(!rustc||stat(rustc,&a)||stat("/proc/self/exe",&b)||a.st_dev!=b.st_dev||a.st_ino!=b.st_ino)return 0;
 char cmd[196608];int fd=open("/proc/self/cmdline",O_RDONLY);require(fd>=0);ssize_t n=read(fd,cmd,sizeof(cmd));close(fd);require(n>0&&n<(ssize_t)sizeof(cmd)&&cmd[n-1]==0);
 int right_name=0,right_kind=0;
 for(char *p=cmd;p<cmd+n;p+=strlen(p)+1){
  char *value=p+strlen(p)+1;if(value>=cmd+n)break;
  if(!strcmp(p,"--crate-name")&&!strcmp(value,"ruff"))right_name=1;
  if(!strcmp(p,"--crate-type")&&(!strcmp(value,"lib")||!strcmp(value,"rlib")))right_kind=1;
 }
 target=right_name&&right_kind?1:2;
 return target==1;
}
static void *symbol(const char *name,uintptr_t offset){
 void *p=dlsym(RTLD_NEXT,name);Dl_info info;require(p&&dladdr(p,&info));require((uintptr_t)p-(uintptr_t)info.dli_fbase==offset);
 require(!base||base==(uintptr_t)info.dli_fbase);base=(uintptr_t)info.dli_fbase;return p;
}
static FILE *dest(const char *name){
 char path[1024];const char *d=getenv("OHM_GRAPH_DIR");require(d!=NULL);int n=snprintf(path,sizeof(path),"%s/%s",d,name);require(n>0&&(size_t)n<sizeof(path));
 FILE *f=fopen(path,"wbx");require(f!=NULL);require(!setvbuf(f,NULL,_IOFBF,1u<<19));return f;
}
static void same_thread(void){pid_t t=gettid();require(!writer||writer==t);writer=t;}
static void put(FILE*f,const void*v,size_t n){require(!n||fwrite(v,1,n,f)==n);}
static void u64(FILE*f,uint64_t n){put(f,&n,8);}
void record(void*,const void*) __asm__(REC);
void record(void*p,const void*to){
 static void(*real)(void*,const void*);if(!real)real=symbol(REC,0x600e7c0);
 if(in_target()){same_thread();const uintptr_t*b=p;size_t n=b[2];require(n<100000);
  if(n&&*(unsigned char*)(b[1]+(n-1)*16)){size_t from=*(const size_t*)(b[1]+16*n-8);require(from<b[5]);if(!regs)regs=dest("register.bin");
   put(regs,(void*)(b[4]+48*from),32);put(regs,to,32);u64(regs,(uintptr_t)__builtin_return_address(0)-base);}
 }
 real(p,to);
}
void add(void*,const void*,uint64_t,uint64_t) __asm__(ADD);
void add(void*p,const void*node,uint64_t a,uint64_t b){
 static void(*real)(void*,const void*,uint64_t,uint64_t);if(!real)real=symbol(ADD,0x6017a00);
 if(in_target()){same_thread();if(!payloads)payloads=dest("payload.bin");put(payloads,node,32);u64(payloads,a);u64(payloads,b);u64(payloads,(uintptr_t)__builtin_return_address(0)-base);}
 real(p,node,a,b);
}
uintptr_t build(void*,const uintptr_t*,void*,void*,void*) __asm__(BUILD);
uintptr_t build(void*out,const uintptr_t*g,void*hash,void*tcx,void*hcx){
 static uintptr_t(*real)(void*,const uintptr_t*,void*,void*,void*);if(!real)real=symbol(BUILD,0x2b2c400);
 if(in_target()){same_thread();require(!graph);graph=dest("graph.bin");size_t n=g[2];require(n>=100&&n<2000000&&g[6]==n);u64(graph,n);put(graph,(void*)g[1],64*n);
  require((g[9]==n)!=(g[12]==n));const uintptr_t*e=g[9]==n?g+7:g+10,*r=g[9]==n?g+10:g+7;
  require(r[2]<=n);u64(graph,r[2]);put(graph,(void*)r[1],8*r[2]);const uintptr_t*all=(void*)e[1];
  for(size_t i=0;i<n;i++){const uintptr_t*v=all+3*i;require(v[2]<=n&&v[2]<=v[0]);u64(graph,v[2]);put(graph,(void*)v[1],8*v[2]);}
  require(!fflush(graph));if(regs)require(!fflush(regs));if(payloads)require(!fflush(payloads));
 }
 return real(out,g,hash,tcx,hcx);
}
