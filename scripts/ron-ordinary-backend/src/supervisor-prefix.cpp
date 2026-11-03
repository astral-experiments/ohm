// Charged outer control. A receipt is published only after normal rustc exits successfully.
#include <openssl/evp.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
namespace fs=std::filesystem;
using std::string;
static void check(bool ok) { if(!ok){perror("Ron supervisor");exit(118);} }
static string hex(const unsigned char* p) { static const char chars[]="0123456789abcdef";string out;
  for(int i=0;i<32;++i){out.push_back(chars[p[i]>>4]);out.push_back(chars[p[i]&15]);}return out;
}
static string sum(const string& s) {unsigned char bytes[32];unsigned n=0;check(EVP_Digest(s.data(),s.size(),bytes,&n,EVP_sha256(),nullptr)&&n==32);return hex(bytes);}
static string physical(const fs::path& file) {
  int fd=open(file.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);check(fd>=0);struct stat before{},after{};
  check(!fstat(fd,&before)&&S_ISREG(before.st_mode));auto* ctx=EVP_MD_CTX_new();check(ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),nullptr));
  std::vector<unsigned char> buf(256*1024);ssize_t n;
  while((n=read(fd,buf.data(),buf.size()))>0)check(EVP_DigestUpdate(ctx,buf.data(),size_t(n)));
  check(n==0 && !fstat(fd,&after) && before.st_size==after.st_size &&
        before.st_ctim.tv_sec==after.st_ctim.tv_sec && before.st_ctim.tv_nsec==after.st_ctim.tv_nsec);
  unsigned char h[32];unsigned count;check(EVP_DigestFinal_ex(ctx,h,&count)&&count==32);
  EVP_MD_CTX_free(ctx);close(fd);return hex(h);
}
static string contents(const fs::path& p,size_t max) {std::ifstream f(p,std::ios::binary);check(f.good());
  f.seekg(0,std::ios::end);auto n=f.tellg();check(n>=0 && size_t(n)<=max);string s(size_t(n),'\0');f.seekg(0);f.read(s.data(),n);check(f.good());return s;}
static std::vector<string> fields(const string& s,char sep) {std::vector<string> v;size_t p=0;
  for(;;){auto k=s.find(sep,p);v.push_back(s.substr(p,k-p));if(k==s.npos)break;p=k+1;}return v;}
struct Member {size_t offset,size;string sha;};
static std::map<string,Member> archive(const string& bytes) {
  check(bytes.compare(0,8,"!<arch>\n")==0);std::map<string,Member> members;string longnames;size_t at=8;
  while(at<bytes.size()){check(at+60<=bytes.size()&&bytes.compare(at+58,2,"`\n")==0);
    auto name=bytes.substr(at,16);name.erase(name.find_last_not_of(' ')+1);
    auto digits=bytes.substr(at+48,10);size_t n=stoul(digits);at+=60;check(n<=bytes.size()-at);
    if(name=="//")longnames=bytes.substr(at,n);
    else if(name!="/" && name!="/SYM64/"){
      if(name[0]=='/'){size_t start=stoul(name.substr(1)),end=longnames.find("/\n",start);check(end!=string::npos);name=longnames.substr(start,end-start);}
      else if(name.back()=='/')name.pop_back();
      check(!name.empty()&&name.find('/')==name.npos&&members.emplace(name,Member{at,n,sum(bytes.substr(at,n))}).second);
    }
    at+=n+(n%2);
  }
  check(at==bytes.size()&&members.size()==12&&members.count("lib.rmeta")&&members.count("lib.rmeta-link"));return members;
}
static void publish(const string& cmd,const string& tool) {
  auto objects=archive(contents(getenv("OHM_RON_ARCHIVE"),8u<<20));
  std::map<string,string> rows,names;std::ifstream trace(getenv("OHM_RON_OBSERVATIONS"));check(trace.good());
  string line;while(std::getline(trace,line)){auto f=fields(line,'\t');if(f[0]=="opt"){
    check(f.size()==12&&rows.emplace(f[1],line).second);
  }else if(f[0]=="emit"){check(f.size()==5 && f[3].empty() && f[4]=="1" && names.emplace(f[1],fs::path(f[2]).filename()).second);}}
  check(rows.size()==10&&names.size()==10);string body="RON-LIVE-02\t"+cmd+"\t"+tool+"\n";
  for(auto& row:rows){auto name=names.at(row.first);auto m=objects.at(name);body+=row.second+"\t"+name+"\t"+
      std::to_string(m.offset)+"\t"+std::to_string(m.size)+"\t"+m.sha+"\n";}
  body+="seal\t"+sum(body)+"\n";fs::path dest(getenv("OHM_RON_RECEIPT"));string tmp=dest.string()+".complete";
  int f=open(tmp.c_str(),O_CREAT|O_EXCL|O_CLOEXEC|O_WRONLY|O_NOFOLLOW,0600);check(f>=0);
  check(write(f,body.data(),body.size())==(ssize_t)body.size());check(!fsync(f));check(!close(f));check(!rename(tmp.c_str(),dest.c_str()));
}
