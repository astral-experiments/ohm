#include "generation.h"
extern char **environ;
static int launch(char** args,std::vector<char*>* env,pid_t& child,long& rss,Held* held) {
  child=fork();check(child>=0);
  if(!child){execve(args[0],args,env?env->data():environ);_exit(119);}
  int status;struct rusage usage{};
  for(;;){
    // A signal invalidates this attempt. Preserve Cargo jobserver tokens by letting
    // the provisional compiler close its RAII tokens before the ordinary retry.
    if(held && broken)held->release();
    if(wait4(child,&status,0,&usage)==child)break;
    check(errno==EINTR);
  }
  rss=usage.ru_maxrss;
  return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
int main(int argc,char**argv) {
  check(argc>3);string mode=argv[1];bool want=mode=="reuse";check(want||mode=="stock");
  string raw;for(int i=3;i<argc;i++){raw+=argv[i];raw.push_back('\0');}
  const char* load=getenv("LD_PRELOAD");
  const char* libs=getenv("LD_LIBRARY_PATH");
  const string base=(fs::path(argv[2]).parent_path().parent_path()/"lib").string();
  bool loader_ok=(!load||!*load) && libs && base==libs;
  for(const char* k: {"LD_AUDIT","LD_PROFILE","LD_DEBUG","LLVM_PROFILE_FILE","GLIBC_TUNABLES","OPENSSL_CONF","OPENSSL_MODULES"})
    if(const char* v=getenv(k);v&&*v)loader_ok=false;
  Held held;string token;bool active=want&&loader_ok&&sum(raw)==REGISTERED_CMD&&held.acquire(argv[2],token);
  if(want&&!loader_ok)held.why="custom-loader";
  if(want && sum(raw)!=REGISTERED_CMD)held.why="different-argv";
  if(active) {
    if(const char* barrier=getenv("OHM_RON_PRIVATE_HOLD_TEST")){
      {std::ofstream f(string(barrier)+".ready");f<<getpid()<<"\n";}
      for(int i=0;i<10000 && !fs::exists(string(barrier)+".go") && !broken;i++)usleep(2000);
      if(!fs::exists(string(barrier)+".go") && !broken){held.why="barrier-timeout";active=false;}
    }
    if(!held.valid()){held.why="writer-before-exec";active=false;}
  }
  if(!active)held.release();
  std::vector<string> stable;std::vector<char*> env;int pipefd[2]{-1,-1};
  if(active){
    check(pipe2(pipefd,O_CLOEXEC)==0 && ron_inherit_new_fd(pipefd[1]));
    string numbers;
    for(int fd:held.fds){if(!numbers.empty())numbers+=',';numbers+=std::to_string(fd);}
    stable.push_back("OHM_RON_ROLE_FDS="+numbers);
    stable.push_back("OHM_RON_NOTIFY_FD="+std::to_string(pipefd[1]));
    for(auto e=environ;*e;++e){string v=*e;if(v.rfind("OHM_RON_ROLE_FDS=",0)!=0&&v.rfind("OHM_RON_NOTIFY_FD=",0)!=0&&v.rfind("LD_PRELOAD=",0)!=0&&v.rfind("OHM_RON_TOOL=",0)!=0&&v.rfind("OHM_RON_MODE=",0)!=0)stable.push_back(std::move(v));}
    stable.push_back(string("LD_PRELOAD=")+getenv("OHM_RON_PAID_PLUGIN"));stable.push_back("OHM_RON_MODE=reuse");stable.push_back("OHM_RON_TOOL="+token);
    for(auto& e:stable)env.push_back(e.data());env.push_back(nullptr);
  }
  pid_t child;long rss=0; int rc=launch(argv+2,active?&env:nullptr,child,rss,active?&held:nullptr);
  pid_t first=child;char marked=0;
  if(active){
    close(pipefd[1]);char messages[64];ssize_t n=read(pipefd[0],messages,sizeof(messages));close(pipefd[0]);
    marked=n==1?messages[0]:'X';
    bool still_held=held.valid();
    if(!still_held || marked=='X' || (marked=='B' && !held.still_named())) {
      held.why=marked=='X'?"codegen-map-invalidated":still_held?"renamed-during-compile":"writer-during-compile";held.release();active=false;
      // The provisional compiler result is never returned. The normal compiler produces
      // the final verdict/outputs for the current software after the private generation changed.
      rc=launch(argv+2,nullptr,child,rss,nullptr);
    } else if(marked!='B'){held.why="loaded-generation-refused";active=false;}
  }
  if(active&&!rc)publish(sum(raw),token);
  std::ofstream gate(getenv("OHM_RON_GATE"));gate<<held.why<<" "<<int(marked)<<" "<<first<<" "<<child<<"\n";
  std::ofstream fd(getenv("OHM_RON_PAID_TERMINAL"));fd<<getpid()<<" "<<child<<" "<<rc<<" "<<rss;
  if(active)fd<<" "<<token;fd<<"\n";
  return rc;
}
