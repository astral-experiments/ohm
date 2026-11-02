#include <llvm-c/Core.h>
#include <llvm-c/BitReader.h>
#include <llvm-c/TargetMachine.h>
#include <llvm-c/Transforms/PassBuilder.h>
#include <valgrind/callgrind.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"failed %d\n",__LINE__);return 1;}}while(0)
typedef struct {uint8_t *bytes;size_t n;unsigned calls;} Result;
static void copy(void *ctx,const uint8_t *bytes,size_t n) {
 Result *r=ctx;r->calls++;if(r->calls!=1 || n<53 || n>16u*1024*1024)abort();
 r->bytes=malloc(n);if(!r->bytes)abort();memcpy(r->bytes,bytes,n);r->n=n;
}
int main(int argc,char **argv){
 REQUIRE(argc==5);void *so=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);REQUIRE(so);
 _Bool (*run)(LLVMModuleRef,void*,void(*)(void*,const uint8_t*,size_t))=dlsym(so,"LLVMRustGetSourcePlacement");REQUIRE(run);
 int fd=atoi(argv[2]);struct stat st;REQUIRE(fd>2 && !fstat(fd,&st) && st.st_size>0 && st.st_size<(32ll<<20));
 size_t n=st.st_size;char *body=malloc(n);REQUIRE(body);for(size_t at=0;at<n;){ssize_t r=read(fd,body+at,n-at);REQUIRE(r>0);at+=r;}
 int price_parse=!strncmp(argv[4],"parse",5);
 if(price_parse){CALLGRIND_START_INSTRUMENTATION;CALLGRIND_ZERO_STATS;}
 LLVMContextRef c=LLVMContextCreate();LLVMMemoryBufferRef b=LLVMCreateMemoryBufferWithMemoryRangeCopy(body,n,"captured-input");
 LLVMModuleRef m=NULL; REQUIRE(!LLVMParseBitcodeInContext2(c,b,&m));free(body);LLVMDisposeMemoryBuffer(b);
 size_t namelen=0;const char *name=LLVMGetSourceFileName(m,&namelen);LLVMSetModuleIdentifier(m,name,namelen);
 if(price_parse){CALLGRIND_STOP_INSTRUMENTATION;}
 /* Real ordinary O1 precedes the new hook on this continuously live LLVM module. */
 LLVMInitializeX86TargetInfo();LLVMInitializeX86Target();LLVMInitializeX86TargetMC();LLVMInitializeX86AsmPrinter();LLVMInitializeX86AsmParser();
 LLVMTargetRef target=NULL; char *error=NULL;
 REQUIRE(!LLVMGetTargetFromTriple("x86_64-unknown-linux-gnu",&target,&error));
 LLVMTargetMachineRef tm=LLVMCreateTargetMachine(target,"x86_64-unknown-linux-gnu","x86-64","",LLVMCodeGenLevelLess,LLVMRelocPIC,LLVMCodeModelDefault);REQUIRE(tm);
 LLVMPassBuilderOptionsRef options=LLVMCreatePassBuilderOptions();REQUIRE(options);
 REQUIRE(!LLVMRunPasses(m,"default<O1>",tm,options));
 LLVMDisposePassBuilderOptions(options);LLVMDisposeTargetMachine(tm);
 Result out={0};uint8_t key[32]={0};size_t len=0;_Bool eligible=0;
 if(!price_parse){CALLGRIND_START_INSTRUMENTATION;CALLGRIND_ZERO_STATS;}
 eligible=run(m,&out,copy);
 if(eligible){REQUIRE(out.bytes && out.calls==1 && !memcmp(out.bytes,"OSP\1",4));memcpy(key,out.bytes+4,sizeof key);len=out.n;free(out.bytes);}
 if(!price_parse){CALLGRIND_STOP_INSTRUMENTATION;}
 REQUIRE(eligible);printf("%s %s ",argv[3],argv[4]);for(unsigned i=0;i<32;i++)printf("%02x",key[i]);printf(" %zu\n",len);
 LLVMDisposeModule(m);LLVMContextDispose(c);dlclose(so);return 0;
}
