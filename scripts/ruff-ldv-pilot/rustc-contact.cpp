#include "guard-v2.cpp"
#include "llvm/Plugins/PassPlugin.h"

extern "C" __attribute__((visibility("default"))) llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "ohm-debug-range-probe", LLVM_VERSION_STRING,
          [](llvm::PassBuilder &) {}, nullptr};
}
