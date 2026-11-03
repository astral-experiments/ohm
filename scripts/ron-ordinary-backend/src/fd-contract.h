// The diagnostic uses only FDs allocated to it by open/pipe. Cargo owns every
// descriptor that was already open, including its jobserver and build watchers.
#pragma once
#include <climits>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
inline bool ron_inherit_new_fd(int fd) {
  return fd>=3 && fcntl(fd,F_SETFD,0)==0;
}
inline int ron_contact_fd(const char* name, unsigned slot=0) {
  const char* p=getenv(name);
  while(p && slot--){p=strchr(p,',');if(p)++p;}
  if(!p||!*p)return -1;
  int n=0;
  for(;*p&&*p!=',';++p){
    const int d=*p-'0';
    if(d<0||d>9||n>(INT_MAX-d)/10)return -1;
    n=n*10+d;
  }
  return n>=3?n:-1;
}
