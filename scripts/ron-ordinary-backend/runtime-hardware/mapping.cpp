#include "fd-contract.h"
// Check the current running image, including every named executable mapping. No filename match is sufficient.
#include "runtime_fds.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <link.h>
#include <mutex>
#include <string>
#include <sys/auxv.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <vector>
extern "C" bool registered_diagnostic_trampoline(unsigned long);
namespace {
struct Mapping {unsigned long start,end,offset,inode;unsigned ma,mi;bool execute,writable;std::string path;};
struct View {
  std::array<struct stat,role_count> files{};
  std::array<unsigned,role_count> seen{},pieces{};
  std::vector<Mapping> maps;
  std::vector<std::string> unknown;
  bool ok=true;
  int slot(const Mapping& m)const {
    for(int i=0;i<role_count;i++)if(files[i].st_ino==m.inode && major(files[i].st_dev)==m.ma && minor(files[i].st_dev)==m.mi)return i;
    return -1;
  }
};
int image(dl_phdr_info* item,size_t,void* context) {
  auto& v=*static_cast<View*>(context);int id=-1;
  if(item->dlpi_addr==getauxval(AT_SYSINFO_EHDR) && item->dlpi_name && !strncmp(item->dlpi_name,"linux-vdso.",11))return 0;
  for(int i=0;i<item->dlpi_phnum;i++){
    const auto& p=item->dlpi_phdr[i];if(p.p_type!=PT_LOAD||!p.p_filesz)continue;
    unsigned long start=item->dlpi_addr+p.p_vaddr,loc=start,end=start+p.p_filesz;
    while(loc<end){
      auto m=std::find_if(v.maps.begin(),v.maps.end(),[&](const Mapping&r){return r.start<=loc&&loc<r.end;});
      int actual=m==v.maps.end()?-1:v.slot(*m);
      if(actual<0 || (id>=0 && actual!=id) || m->offset+loc-m->start!=p.p_offset+loc-start){
        v.ok=false;v.unknown.push_back(std::string("image ")+(item->dlpi_name?item->dlpi_name:"<null>")+" "+(m==v.maps.end()?"<absent>":m->path));
        return 0;
      }
      id=actual;++v.pieces[id];loc=std::min(end,m->end);
    }
  }
  if(id>=0)++v.seen[id];else v.ok=false;
  return 0;
}
std::mutex serial;
std::atomic<bool> invalidated{};
bool inspect(const char* phase,bool startup) {
  std::lock_guard<std::mutex> lock(serial);
  if(invalidated.load())return false;
  View v;FILE* maps=fopen("/proc/self/maps","re");if(!maps)return false;
  char* line=nullptr;size_t cap=0;
  while(getline(&line,&cap,maps)>0){
    Mapping m{};char perms[6]{};int used=0;
    if(sscanf(line,"%lx-%lx %4s %lx %x:%x %lu %n",&m.start,&m.end,perms,&m.offset,&m.ma,&m.mi,&m.inode,&used)!=7)continue;
    m.execute=strchr(perms,'x');m.writable=strchr(perms,'w');m.path=line+used;if(!m.path.empty()&&m.path.back()=='\n')m.path.pop_back();
    v.maps.push_back(std::move(m));
  }
  free(line);fclose(maps);
  for(int i=0;i<role_count;i++)if(fstat(ron_contact_fd("OHM_RON_ROLE_FDS",i),&v.files[i]) || fcntl(ron_contact_fd("OHM_RON_ROLE_FDS",i),F_GETLEASE)!=F_RDLCK)v.ok=false;
  if(v.ok)dl_iterate_phdr(image,&v);
  for(const auto&m:v.maps)if(m.execute){
    bool known=!m.writable;
    if(m.inode)known=known && !m.path.empty() && m.path.front()=='/' && v.slot(m)>=0;
    else if(m.path=="[vdso]")known=known && m.start==getauxval(AT_SYSINFO_EHDR);
    else if(m.path=="[vsyscall]")known=known && m.start==0xffffffffff600000UL && m.end==m.start+4096;
    else {
      known=known && m.path.empty() && m.start%4096==0 && m.end%4096==0;
      for(auto page=m.start;known && page<m.end;page+=4096)known=registered_diagnostic_trampoline(page);
    }
    if(!known){v.unknown.push_back("unregistered executable "+(m.path.empty()?std::string("<anonymous>"):m.path));v.ok=false;}
  }
  for(int i=0;i<role_count;i++){
    if(i==vg_role || (startup && i==serde_role)){if(v.seen[i]>1)v.ok=false;continue;}
    if(v.seen[i]!=1 || !v.pieces[i])v.ok=false;
  }
  const char* root=getenv("OHM_RON_BINDING");int fd=root?open(root,O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600):-1;
  if(fd<0)return false;
  dprintf(fd,"%s %s %d\n",phase,v.ok?"bound":"refused",getpid());
  for(int i=0;i<role_count;i++)dprintf(fd,"%d %lu %lu %lld %u %u\n",i,(unsigned long)v.files[i].st_dev,(unsigned long)v.files[i].st_ino,(long long)v.files[i].st_size,v.seen[i],v.pieces[i]);
  for(auto& why:v.unknown)dprintf(fd,"unknown %s\n",why.c_str());
  close(fd);
  if(startup || !v.ok){const char note=v.ok?'B':'F';if(write(ron_contact_fd("OHM_RON_NOTIFY_FD"),&note,1)!=1)v.ok=false;}
  if(!v.ok)invalidated.store(true);
  return v.ok;
}
}
extern "C" bool check_held_software(){return inspect("start",true);}
extern "C" bool check_codegen_software(const char* phase){return inspect(phase,false);}
