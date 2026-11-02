#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Target/RegisterTargetPassConfigCallback.h"
#include "llvm/CodeGen/TargetPassConfig.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
static std::atomic<unsigned> OhmInstalls, OhmMachines, OhmDirect, OhmSkips;
__attribute__((destructor)) static void OhmNativeReport() {
  if (std::getenv("OHM_REPORT_NATIVE_PASS"))
    std::fprintf(stderr, "OHM_NATIVE_PIPELINE @ARM@ %u %u %u %u\n",
          OhmInstalls.load(), OhmMachines.load(), OhmDirect.load(), OhmSkips.load());
}
