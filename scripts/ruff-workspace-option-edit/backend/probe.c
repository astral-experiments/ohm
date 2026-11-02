#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef NATIVE_PMU
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#else
#include <valgrind/callgrind.h>
#endif

typedef void *Ref;
#define REQUIRE(x)                                                             \
  do {                                                                         \
    if (!(x)) {                                                                \
      fprintf(stderr, "line %d: %s (errno %d)\n", __LINE__, #x, errno);        \
      exit(3);                                                                 \
    }                                                                          \
  } while (0)
#ifdef NATIVE_PMU
static int counter;
static void begin_count(void) {
  REQUIRE(!ioctl(counter, PERF_EVENT_IOC_RESET, 0));
  REQUIRE(!ioctl(counter, PERF_EVENT_IOC_ENABLE, 0));
}
static void end_count(void) {
  REQUIRE(!ioctl(counter, PERF_EVENT_IOC_DISABLE, 0));
}
static void configure_clock(void) {
  struct perf_event_attr attr = {0};
  attr.type = PERF_TYPE_HARDWARE;
  attr.size = sizeof attr;
  attr.config = PERF_COUNT_HW_INSTRUCTIONS;
  attr.disabled = 1;
  attr.inherit = 1;
  attr.pinned = 1;
  attr.exclude_kernel = 1;
  attr.exclude_hv = 1;
  attr.read_format =
      PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
  counter =
      (int)syscall(SYS_perf_event_open, &attr, 0, -1, -1, PERF_FLAG_FD_CLOEXEC);
  REQUIRE(counter >= 0);
}
static void report_clock(void) {
  uint64_t a[3] = {0};
  REQUIRE(read(counter, a, sizeof a) == sizeof a && a[1] && a[2] &&
          a[2] <= a[1]);
  REQUIRE(a[1] - a[2] <= a[1] / 1000);
  printf("PMU instructions %" PRIu64 " enabled %" PRIu64 " running %" PRIu64
         "\n",
         a[0], a[1], a[2]);
  REQUIRE(!close(counter));
}
#else
#define configure_clock() ((void)0)
#define report_clock() ((void)0)
#define begin_count()                                                          \
  do {                                                                         \
    CALLGRIND_ZERO_STATS;                                                      \
    CALLGRIND_TOGGLE_COLLECT;                                                  \
  } while (0)
#define end_count()                                                            \
  do {                                                                         \
    CALLGRIND_TOGGLE_COLLECT;                                                  \
  } while (0)
#endif
static void *lib;
static void *symbol(const char *name) {
  void *p = dlsym(lib, name);
  REQUIRE(p);
  return p;
}
#define LOAD(type, name) type name = (type)symbol(#name)
typedef Ref (*Zero)(void);
typedef void (*Init)(void);
typedef void (*Free)(Ref);
typedef Ref (*Input)(const char *, size_t, const char *);
typedef int (*Parse)(Ref, Ref, Ref *);
typedef int (*Target)(const char *, Ref *, char **);
typedef Ref (*Machine)(Ref, const char *, const char *, const char *, int, int,
                       int);
typedef Ref (*Passes)(Ref, const char *, Ref, Ref);
typedef int (*Emit)(Ref, Ref, int, char **, Ref *);
typedef char *(*Message)(Ref);
typedef const char *(*Bytes)(Ref);
typedef size_t (*Size)(Ref);

int main(int argc, char **argv) {
  REQUIRE(argc == 7);
  const char *mode = argv[4], *phase = argv[5];
  const int lean = !strcmp(mode, "lean") || !strcmp(mode, "both");
  const int fast = !strcmp(mode, "fast") || !strcmp(mode, "both");
  REQUIRE(lean || fast || !strcmp(mode, "normal"));
  int measure_ir = !strcmp(phase, "ir"), measure_obj = !strcmp(phase, "obj");
  REQUIRE(measure_ir || measure_obj || !strcmp(phase, "sham") ||
          !strcmp(phase, "cal"));
  lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  REQUIRE(lib);
  LOAD(Zero, LLVMContextCreate);
  LOAD(Zero, LLVMCreatePassBuilderOptions);
  LOAD(Input, LLVMCreateMemoryBufferWithMemoryRangeCopy);
  LOAD(Parse, LLVMParseBitcodeInContext2);
  LOAD(Target, LLVMGetTargetFromTriple);
  LOAD(Machine, LLVMCreateTargetMachine);
  LOAD(Passes, LLVMRunPasses);
  LOAD(Emit, LLVMTargetMachineEmitToMemoryBuffer);
  LOAD(Bytes, LLVMGetBufferStart);
  LOAD(Size, LLVMGetBufferSize);
  LOAD(Free, LLVMDisposeModule);
  LOAD(Free, LLVMContextDispose);
  LOAD(Free, LLVMDisposeMemoryBuffer);
  LOAD(Free, LLVMDisposeTargetMachine);
  LOAD(Free, LLVMDisposePassBuilderOptions);
  LOAD(Message, LLVMGetErrorMessage);
  const char *inits[] = {"LLVMInitializeX86TargetInfo",
                         "LLVMInitializeX86Target", "LLVMInitializeX86TargetMC",
                         "LLVMInitializeX86AsmPrinter",
                         "LLVMInitializeX86AsmParser"};
  for (size_t i = 0; i < sizeof inits / sizeof *inits; i++)
    ((Init)symbol(inits[i]))();
  struct stat signed_file, mapped_file;
  Dl_info where;
  REQUIRE(dladdr((void *)LLVMRunPasses, &where) &&
          !stat(where.dli_fname, &mapped_file) && !stat(argv[1], &signed_file));
  REQUIRE(signed_file.st_dev == mapped_file.st_dev &&
          signed_file.st_ino == mapped_file.st_ino);
  int fd = open(argv[2], O_RDONLY | O_NOFOLLOW);
  struct stat st;
  REQUIRE(fd >= 0 && !fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_size > 0 &&
          st.st_size < 32 * 1024 * 1024);
  size_t n = (size_t)st.st_size;
  char *body = malloc(n);
  REQUIRE(body);
  for (size_t at = 0; at < n;) {
    ssize_t readlen = read(fd, body + at, n - at);
    REQUIRE(readlen > 0);
    at += (size_t)readlen;
  }
  REQUIRE(!close(fd));
  Ref cx = LLVMContextCreate(), mod = NULL,
      buf =
          LLVMCreateMemoryBufferWithMemoryRangeCopy(body, n, "pinned-ruff-cgu");
  REQUIRE(cx && buf && !LLVMParseBitcodeInContext2(cx, buf, &mod) && mod);
  LLVMDisposeMemoryBuffer(buf);
  free(body);
  const char *triple = "x86_64-unknown-linux-gnu";
  Ref target = NULL;
  char *err = NULL;
  REQUIRE(!LLVMGetTargetFromTriple(triple, &target, &err) && target);
  Ref tm = LLVMCreateTargetMachine(target, triple, "x86-64", "", fast ? 0 : 1,
                                   2, 0),
      pbo = LLVMCreatePassBuilderOptions(), out = NULL;
  REQUIRE(tm && pbo);
  const char *pipeline = lean ? "always-inline,function(sroa,early-cse,"
                                "instcombine,simplifycfg),globaldce"
                              : "default<O1>";
  volatile uint64_t calibration = 0;
  configure_clock();
  if (!strcmp(phase, "sham") || !strcmp(phase, "cal")) {
    begin_count();
    if (phase[0] == 'c')
      for (uint64_t k = 1; k <= 100000; k++)
        calibration += k;
    end_count();
  }
  if (measure_ir) {
    begin_count();
  }
  Ref irerr = LLVMRunPasses(mod, pipeline, tm, pbo);
  if (measure_ir) {
    end_count();
  }
  if (irerr) {
    fprintf(stderr, "LLVM pipeline: %s\n", LLVMGetErrorMessage(irerr));
    return 4;
  }
  if (measure_obj) {
    begin_count();
  }
  int emit = LLVMTargetMachineEmitToMemoryBuffer(tm, mod, 1, &err, &out);
  if (measure_obj) {
    end_count();
  }
  report_clock();
  REQUIRE(!emit && out && LLVMGetBufferSize(out) > 64 &&
          !memcmp(LLVMGetBufferStart(out), "\177ELF", 4));
  FILE *f = fopen(argv[3], "wb");
  REQUIRE(f);
  REQUIRE(fwrite(LLVMGetBufferStart(out), 1, LLVMGetBufferSize(out), f) ==
              LLVMGetBufferSize(out) &&
          !fclose(f));
  printf("LLVM inode %ju/%ju object %zu input %zu calibration %" PRIu64
         " tag %s\n",
         (uintmax_t)mapped_file.st_dev, (uintmax_t)mapped_file.st_ino,
         LLVMGetBufferSize(out), n, calibration, argv[6]);
  LLVMDisposeMemoryBuffer(out);
  LLVMDisposePassBuilderOptions(pbo);
  LLVMDisposeTargetMachine(tm);
  LLVMDisposeModule(mod);
  LLVMContextDispose(cx);
  return 0;
}
