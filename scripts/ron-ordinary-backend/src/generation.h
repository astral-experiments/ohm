// All leases are private, read-only, generation-bound and limited to this process invocation.
#include "blake3.h"
#include <cerrno>
#include <csignal>
#include <poll.h>
static volatile sig_atomic_t broken;
static void lease_request(int) {broken=1;}
struct Held {
  int fds[3]{-1,-1,-1};
  fs::path names[3];
  const char *why="not-selected";
  bool acquire(const fs::path& front,string& token) {
    fs::path dir=front.parent_path().parent_path()/"lib";
    fs::path files[]={front,dir/"librustc_driver-b03bf00bec23bb9a.so",dir/"libLLVM.so.23.1-rust-1.99.0-beta"};
    const char* wanted[]={"018abf8350a8017d69a58277ef4d48cdc6e25f03115231ea57728bec958dcc96",
      "e2239702579fabe35c3af415497e3003c75a05ae68e05b6b2d94fa04d47f1461",
      "386b6d6db58416a5d83b874d1feba7814a2c17d275ab7cf04d9d3f081af039eb"};
    struct sigaction sa{};sa.sa_handler=lease_request;sigemptyset(&sa.sa_mask);check(sigaction(SIGIO,&sa,nullptr)==0);
    string binding="RON-HELD-B3-01\n";std::vector<unsigned char> buf(262144);
    for(int i=0;i<3;i++){
      names[i]=files[i];
      int raw=open(files[i].c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat before{},after{};
      if(raw<0){why="missing";return false;}
      if(fstat(raw,&before)||!S_ISREG(before.st_mode)||before.st_uid!=getuid()||before.st_nlink!=1){
        close(raw);why="outside-private-eligible-install";return false;
      }
      if(fcntl(190+i,F_GETFD)!=-1||errno!=EBADF || dup2(raw,190+i)!=190+i){close(raw);why="occupied-descriptor";return false;}
      close(raw);int fd=fds[i]=190+i;
      if(fcntl(fd,F_SETOWN,getpid())||fcntl(fd,F_SETLEASE,F_RDLCK)){why="writer-or-lease-unavailable";return false;}
      blake3_hasher hash;blake3_hasher_init(&hash);size_t total=0;ssize_t n=0;
      for(;;){
        if(broken)break;
        n=read(fd,buf.data(),buf.size());
        if(n<0&&errno==EINTR)continue;
        if(n<=0)break;
        total+=size_t(n);blake3_hasher_update(&hash,buf.data(),size_t(n));
      }
      unsigned char digest[32];blake3_hasher_finalize(&hash,digest,32);
      if(broken||n!=0||total!=size_t(before.st_size)||fstat(fd,&after)||before.st_dev!=after.st_dev||before.st_ino!=after.st_ino||
         before.st_ctim.tv_sec!=after.st_ctim.tv_sec||before.st_ctim.tv_nsec!=after.st_ctim.tv_nsec||
         fcntl(fd,F_GETLEASE)!=F_RDLCK){why="broken-during-read";return false;}
      auto value=hex(digest);if(value!=wanted[i]){why="different-tool-bytes";return false;}binding+=value+"\n";
    }
    token=sum(binding);why="acquired";return true;
  }
  bool valid()const {return !broken && fds[0]>=0 && fds[1]>=0 && fds[2]>=0 &&
    fcntl(fds[0],F_GETLEASE)==F_RDLCK && fcntl(fds[1],F_GETLEASE)==F_RDLCK && fcntl(fds[2],F_GETLEASE)==F_RDLCK;}
  bool still_named()const {
    for(int i=0;i<3;i++){
      struct stat held{},named{};
      if(fds[i]<0||fstat(fds[i],&held)||lstat(names[i].c_str(),&named)||!S_ISREG(named.st_mode)||
         held.st_dev!=named.st_dev||held.st_ino!=named.st_ino)return false;
    }
    return true;
  }
  void release() {for(int& fd:fds)if(fd>=0){(void)fcntl(fd,F_SETLEASE,F_UNLCK);close(fd);fd=-1;}}
  ~Held(){release();}
};
