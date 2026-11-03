#include <link.h>
#include <cstring>
extern "C" bool check_held_software();
static int owner_is_loaded(dl_phdr_info* info,size_t,void* context) {
  const char* name=strrchr(info->dlpi_name,'/');
  if(name && strcmp(name+1,"librustc_driver-b03bf00bec23bb9a.so")==0)
    ++*static_cast<unsigned*>(context);
  return 0;
}
// Isolated Linux x86-64 contact for the fixed signed compiler. All signed files stay intact.
#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Bitcode/BitcodeWriter.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Module.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Target/TargetMachine.h"
#include <openssl/sha.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <link.h>
#include <map>
#include <mutex>
#include <sys/stat.h>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>

static void require(bool ok) {
  if (!ok) { perror("Ron contact"); _exit(117); }
}
static const char* log_path;
static const char* mode;
static char hexnybble(unsigned c) { return "0123456789abcdef"[c & 15]; }
static std::string digest(const void* data, size_t length) {
  uint8_t bytes[32];
  require(SHA256(static_cast<const unsigned char*>(data), length, bytes) != nullptr);
  std::string s(64, '0');
  for (unsigned i = 0; i != 32; ++i) {
    s[2*i] = hexnybble(bytes[i] >> 4);
    s[2*i+1] = hexnybble(bytes[i]);
  }
  return s;
}
static bool asm_operand(llvm::Value* v, llvm::SmallPtrSetImpl<llvm::Value*>& seen) {
  if (llvm::isa<llvm::InlineAsm>(v)) return true;
  auto* c = llvm::dyn_cast<llvm::Constant>(v);
  if (!c || llvm::isa<llvm::GlobalValue>(v) || !seen.insert(v).second) return false;
  for (llvm::Value* o : c->operands()) if (asm_operand(o, seen)) return true;
  return false;
}
static bool external_asm(llvm::Module& m) {
  if (!m.getModuleInlineAsm().empty()) return true;
  llvm::SmallPtrSet<llvm::Value*, 32> seen;
  for (auto& v : m.globals())
    if (v.hasInitializer() && asm_operand(v.getInitializer(), seen)) return true;
  for (auto& f : m)
    for (auto& bb : f)
      for (auto& i : bb)
        for (auto& op : i.operands()) if (asm_operand(op.get(), seen)) return true;
  return false;
}
static void record(const std::string& row) {
  int fd=open(log_path,O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC,0600);
  require(fd>=0 && write(fd,row.data(),row.size())==(ssize_t)row.size());close(fd);
}
static std::string id(llvm::Module* m) {
  auto n=m->getModuleIdentifier();
  require(!n.empty() && n.find_first_of("\t\r\n") == std::string::npos);
  return n;
}
struct Prior {
  std::string signature, member_name, object_digest;
  size_t offset, length;
};
struct Ready { std::string name, bytes; };
struct Holdings {
  int archive = -1;
  std::map<std::string,Prior> prior;
  std::map<std::string,Ready> ready;
  std::mutex mutex;
};
static Holdings& holdings() { static Holdings value;return value; }
static std::string read_all(const char* path,size_t limit) {
  int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return {};
  std::string data;char buf[4096];ssize_t n;
  while((n=read(fd,buf,sizeof(buf)))>0 && data.size()+size_t(n)<=limit)data.append(buf,size_t(n));
  close(fd);return n==0?data:std::string();
}
static std::vector<std::string> fields(const std::string& s,char delim) {
  std::vector<std::string> result;size_t at=0;
  for(;;){auto p=s.find(delim,at);result.emplace_back(s.substr(at,p-at));if(p==s.npos)break;at=p+1;}
  return result;
}
static void load_receipt() {
  auto& h=holdings();
  auto receipt=read_all(getenv("OHM_RON_RECEIPT"),16384);
  if(receipt.empty())return;
  auto end=receipt.rfind("seal\t");
  if(end==receipt.npos || receipt.substr(end+5)!=digest(receipt.data(),end)+"\n")return;
  auto rows=fields(receipt.substr(0,end),'\n');
  auto cmd=read_all("/proc/self/cmdline",65536);
  auto first=cmd.find(char(0));
  if(first==cmd.npos || rows.size()!=12 || !rows.back().empty())return;
  auto arguments=cmd.substr(first+1);
  if(!getenv("OHM_RON_TOOL") || rows[0]!="RON-LIVE-02\t"+digest(arguments.data(),arguments.size())+"\t"+getenv("OHM_RON_TOOL"))return;
  int fd=open(getenv("OHM_RON_ARCHIVE"),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
  struct stat st{};char magic[8];
  if(fd<0)return;
  if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size<=0 || st.st_size>8*1024*1024 ||
     pread(fd,magic,sizeof(magic),0)!=8 || memcmp(magic,"!<arch>\n",8)){close(fd);return;}
  std::map<std::string,Prior> entries;
  for(size_t i=1;i<=10;++i){
    auto args=fields(rows[i],'\t');
    if(args.size()!=16 || args[0]!="opt" || args[1].size()>128 || args[2].size()!=64 ||
       args[15].size()!=64){close(fd);return;}
    auto nums=[](const std::string& v){
      return !v.empty() && v.size()<10 && v.find_first_not_of("0123456789")==v.npos;
    };
    if(!nums(args[13]) || !nums(args[14])){close(fd);return;}
    size_t offset=strtoul(args[13].c_str(),nullptr,10), length=strtoul(args[14].c_str(),nullptr,10);
    if(length<64 || offset+length>size_t(st.st_size) ||
       args[12].find('/')!=args[12].npos || args[12].find(args[1]+".rcgu.o")==args[12].npos ||
       entries.count(args[1])){close(fd);return;}
    auto suffix=rows[i].size()-args[12].size()-args[13].size()-args[14].size()-args[15].size()-4;
    entries.emplace(args[1],Prior{rows[i].substr(0,suffix),args[12],args[15],offset,length});
  }
  h.archive=fd;h.prior=std::move(entries);
}
static bool select_member(const std::string& name,const std::string& signature) {
  auto& h=holdings();auto it=h.prior.find(name);
  if(it==h.prior.end() || it->second.signature!=signature)return false;
  const auto& p=it->second;std::string bytes(p.length,'\0');size_t at=0;
  while(at<bytes.size()){
    ssize_t n=pread(h.archive,bytes.data()+at,bytes.size()-at,p.offset+at);
    if(n<=0)return false;at+=size_t(n);
  }
  if(memcmp(bytes.data(),"\177ELF\002\001",6) || digest(bytes.data(),bytes.size())!=p.object_digest)
    return false;
  std::lock_guard<std::mutex> lock(h.mutex);
  require(h.ready.emplace(name,Ready{p.member_name,std::move(bytes)}).second);
  return true;
}
extern "C" __attribute__((visibility("hidden"))) int inspect_opt(
    llvm::Module* m, llvm::TargetMachine* target, unsigned level,
    unsigned stage, bool plugin, bool no_pipeline) {
  if (!strcmp(mode,"delegate")) return 0;
  llvm::SmallVector<char, 0> bytes;
  llvm::raw_svector_ostream output(bytes);
  llvm::WriteBitcodeToFile(*m, output, /*ShouldPreserveUseListOrder=*/true);
  auto key=digest(bytes.data(),bytes.size());
  bool assembly=external_asm(*m);
  auto row=std::string("opt\t")+id(m)+"\t"+key+"\t"+std::to_string(bytes.size())+"\t"+
      std::to_string(assembly)+"\t"+target->getTargetTriple().str()+"\t"+
      target->getTargetCPU().str()+"\t"+target->getTargetFeatureString().str()+";reloc="+std::to_string(unsigned(target->getRelocationModel()))+";code="+std::to_string(unsigned(target->getCodeModel()))+";speed="+std::to_string(unsigned(target->getOptLevel()))+"\t"+
      std::to_string(level)+"\t"+std::to_string(stage)+"\t"+std::to_string(plugin)+"\t"+
      std::to_string(no_pipeline)+"\n";
  record(row);
  if(strcmp(mode,"reuse") || assembly || level!=1 || stage!=0 || plugin || no_pipeline)return 0;
  bool matches=select_member(id(m),row.substr(0,row.size()-1));
  if(matches)record("select\t"+id(m)+"\n");
  if(matches)if(const char* wait=getenv("OHM_RON_PRIVATE_OPT_TEST")){
    auto ready=std::string(wait)+".ready",go=std::string(wait)+".go";
    int fd=open(ready.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    if(fd>=0){dprintf(fd,"%d %s\n",getpid(),id(m).c_str());close(fd);}
    for(int t=0;t<30000 && access(go.c_str(),F_OK);++t)usleep(2000);
  }
  return int(matches);
}
extern "C" __attribute__((visibility("hidden"))) int inspect_emit(
    void*, void*, llvm::Module* m, const char* path, const char* dwo, unsigned kind) {
  if (!strcmp(mode,"delegate")) return 0;
  require(path && !strchr(path,'\n'));
  auto name=id(m);
  record(std::string("emit\t")+name+"\t"+path+"\t"+(dwo?dwo:"")+"\t"+std::to_string(kind)+"\n");
  if(strcmp(mode,"reuse"))return 0;
  auto& h=holdings();Ready r;
  {
    std::lock_guard<std::mutex> lock(h.mutex);
    auto found=h.ready.find(name);if(found==h.ready.end())return 0;
    r=std::move(found->second);h.ready.erase(found);
  }
  auto filename=strrchr(path,'/');filename=filename?filename+1:path;
  require(r.name==filename && (!dwo || !*dwo) && kind==1);
  auto tmp=std::string(path)+".ron-verified-"+std::to_string(getpid());
  int fd=open(tmp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0666);
  require(fd>=0);size_t at=0;
  while(at<r.bytes.size()){
    ssize_t n=write(fd,r.bytes.data()+at,r.bytes.size()-at);
    if(n<=0){close(fd);unlink(tmp.c_str());_exit(117);}at+=size_t(n);
  }
  if(close(fd) || rename(tmp.c_str(),path)){unlink(tmp.c_str());_exit(117);}
  record("replaced\t"+name+"\t"+std::to_string(r.bytes.size())+"\n");
  return 1;
}
extern "C" {
__attribute__((visibility("hidden"))) void *opt_trampoline, *emit_trampoline;
void opt_hook(),emit_hook();
}
// Copy only whole instructions verified in the physical signed file. Both fixed
// prefixes contain no RIP-relative operands or branch destinations.
static void jump(unsigned char* dest, const void* target) {
  static const unsigned char op[]={0xff,0x25,0,0,0,0};
  memcpy(dest,op,sizeof(op)); memcpy(dest+sizeof(op),&target,sizeof(target));
}
static void instrument(uintptr_t addr, const unsigned char* prefix, size_t n,
                       void* hook,void** trampoline) {
  require(n>=14 && !memcmp((void*)addr,prefix,n));
  unsigned char* tr=(unsigned char*)mmap(nullptr,4096,PROT_READ|PROT_WRITE,
      MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
  require(tr!=MAP_FAILED);memcpy(tr,prefix,n);jump(tr+n,(void*)(addr+n));
  require(mprotect(tr,4096,PROT_READ|PROT_EXEC)==0);*trampoline=tr;
  void* page=(void*)(addr&~(uintptr_t)4095);require((addr&4095)+n <= 4096);
  require(mprotect(page,4096,PROT_READ|PROT_WRITE)==0);
  jump((unsigned char*)addr,hook);require(mprotect(page,4096,PROT_READ|PROT_EXEC)==0);
}
static int install(dl_phdr_info* info,size_t,void* userdata) {
  if (!strstr(info->dlpi_name,"/librustc_driver-b03bf00bec23bb9a.so")) return 0;
  ++*static_cast<int*>(userdata);
  static const unsigned char opt[]={0xf3,0x0f,0x1e,0xfa,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x55,0x53};
  static const unsigned char emit[]={0xf3,0x0f,0x1e,0xfa,0x41,0x57,0x49,0x89,0xff,0x41,0x56,0x41,0x55,0x41,0x54};
  instrument(info->dlpi_addr+0x6df2240,opt,sizeof(opt),(void*)opt_hook,&opt_trampoline);
  instrument(info->dlpi_addr+0x6be43ce,emit,sizeof(emit),(void*)emit_hook,&emit_trampoline);
  return 0;
}
__attribute__((constructor)) static void init() {
  mode=getenv("OHM_RON_MODE");log_path=getenv("OHM_RON_OBSERVATIONS");
  if (!mode || !log_path) return;
  unsigned owners=0; dl_iterate_phdr(owner_is_loaded,&owners);
  if(owners!=1 || !check_held_software())return;
  int found=0;dl_iterate_phdr(install,&found);require(found<=1);
  if(found && !strcmp(mode,"reuse"))load_receipt();
}
