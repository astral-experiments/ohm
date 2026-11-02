#include <unistd.h>
#include <string.h>
extern char *program_invocation_short_name;
#define S_(v) #v
#define S(v) S_(v)
__attribute__((constructor)) static void loaded(void) {
 const char *n=program_invocation_short_name; if(n && strncmp(n,"constructors-",13)==0) {
 static const char t[]="chosen-gnu-provider-" S(VALUE) "\n"; (void)write(1,t,sizeof(t)-1); } }
