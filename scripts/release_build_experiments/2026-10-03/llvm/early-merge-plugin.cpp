#include "llvm/Config/llvm-config.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Transforms/IPO/GlobalDCE.h"
#include "llvm/Transforms/IPO/MergeFunctions.h"

using namespace llvm;

// Screening only: both plugins restore Ohm's prelink MergeFunctions callback,
// which LLVMPluginsLen != 0 suppresses in rustc's pipeline configuration.
extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "OhmReleaseEarlyMerge", LLVM_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineEarlySimplificationEPCallback(
                [](ModulePassManager &MPM, OptimizationLevel Level,
                   ThinOrFullLTOPhase Phase) {
                  if (Level != OptimizationLevel::O0 &&
                      Phase == ThinOrFullLTOPhase::ThinLTOPreLink)
                    MPM.addPass(MergeFunctionsPass());
                });
#ifdef OHM_EARLY_FULL_LTO_MERGE
            PB.registerFullLinkTimeOptimizationEarlyEPCallback(
                [](ModulePassManager &MPM, OptimizationLevel Level) {
                  if (Level != OptimizationLevel::O0) {
#ifdef OHM_PRUNE_BEFORE_MERGE
                    MPM.addPass(GlobalDCEPass(/*InLTOPostLink=*/true));
#endif
                    MPM.addPass(MergeFunctionsPass());
                  }
                });
#endif
          }};
}
