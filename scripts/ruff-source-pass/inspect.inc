#include <fcntl.h>
#include <limits.h>
#include <unistd.h>
__attribute__((destructor)) static void OhmPhysicalReport() {
  const char *dir = std::getenv("OHM_SOURCE_PASS_AUDIT");
  if (!dir) return;
  char name[PATH_MAX];
  int n = std::snprintf(name, sizeof(name), "%s/%ld.pass", dir, (long)getpid());
  if (n < 0 || (size_t)n >= sizeof(name)) _exit(125);
  int fd = open(name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (fd < 0 || dprintf(fd, "@ARM@ %u %u %u %u\n", OhmInstalls.load(), OhmMachines.load(),
                       OhmDirect.load(), OhmSkips.load()) < 0 || close(fd)) _exit(125);
}
