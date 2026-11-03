#include "fd-contract.h"
// Genuine file-backed PT_LOAD intervals of the running front end, driver and LLVM
// must resolve to the three immutable-for-this-visit descriptions inherited from the verifier.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <link.h>
#include <string>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <vector>
namespace {
struct Mapping { unsigned long start, end, offset, inode; unsigned ma, mi; };
struct Loaded {
  struct stat actual[3]{};
  std::vector<Mapping> maps;
  int seen[3]{}, intervals[3]{};
  bool good=true;
};
int match(dl_phdr_info *entry,size_t,void *ctx) {
  auto& v=*static_cast<Loaded*>(ctx);
  const char *full=entry->dlpi_name,*name=strrchr(full,'/');
  if(name) name++;else name=full;
  int k=!*full ? 0 : !strcmp(name,"librustc_driver-b03bf00bec23bb9a.so") ? 1 :
          strstr(name,"libLLVM") ? 2 : -1;
  if(k<0)return 0;
  ++v.seen[k];auto& s=v.actual[k];
  for(int i=0;i<entry->dlpi_phnum;++i){
    const auto& ph=entry->dlpi_phdr[i];
    if(ph.p_type!=PT_LOAD||!ph.p_filesz)continue;
    unsigned long base=entry->dlpi_addr+ph.p_vaddr,pos=base,end=pos+ph.p_filesz;
    while(pos<end){
      auto m=std::find_if(v.maps.begin(),v.maps.end(),[&](const Mapping& r){return r.start<=pos && pos<r.end;});
      if(m==v.maps.end() || m->inode!=s.st_ino || m->ma!=major(s.st_dev) || m->mi!=minor(s.st_dev) ||
         m->offset+(pos-m->start)!=ph.p_offset+(pos-base)){v.good=false;return 0;}
      ++v.intervals[k];pos=std::min(end,m->end);
    }
  }
  return 0;
}
}
extern "C" bool check_held_software() {
  Loaded v;FILE* f=fopen("/proc/self/maps","re");
  if(!f)return false;
  char* line=nullptr;size_t cap=0;
  while(getline(&line,&cap,f)>0){
    Mapping row{};char prot[6]{};
    if(sscanf(line,"%lx-%lx %4s %lx %x:%x %lu",&row.start,&row.end,prot,&row.offset,&row.ma,&row.mi,&row.inode)==7)v.maps.push_back(row);
  }
  free(line);fclose(f);
  for(int i=0;i<3;++i) if(fstat(ron_contact_fd("OHM_RON_ROLE_FDS",i),&v.actual[i]) || fcntl(ron_contact_fd("OHM_RON_ROLE_FDS",i),F_GETLEASE)!=F_RDLCK)v.good=false;
  if(v.good)dl_iterate_phdr(match,&v);
  for(int j=0;j<3;++j) if(v.seen[j]!=1||!v.intervals[j])v.good=false;
  auto file=getenv("OHM_RON_BINDING");
  int log=file?open(file,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600):-1;
  if(log<0)return false;
  dprintf(log,"%s %d\n",v.good?"bound":"refused",getpid());
  for(int j=0;j<3;++j)dprintf(log,"%d %lu %lu %lld %d %d\n",j,(unsigned long)v.actual[j].st_dev,
         (unsigned long)v.actual[j].st_ino,(long long)v.actual[j].st_size,v.seen[j],v.intervals[j]);
  close(log);
  const char result=v.good?'B':'F';
  return write(ron_contact_fd("OHM_RON_NOTIFY_FD"),&result,1)==1 && v.good;
}
