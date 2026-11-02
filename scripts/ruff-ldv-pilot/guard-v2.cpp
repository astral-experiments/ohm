#include "llvm/CodeGen/LiveDebugValuesPass.h"
#include "llvm/CodeGen/MachineFunctionPass.h"
#include "llvm/CodeGen/Passes.h"
#include "llvm/CodeGen/TargetPassConfig.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/Pass.h"
#include "llvm/Target/RegisterTargetPassConfigCallback.h"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace llvm;

namespace {
enum Reason { Empty, OtherCU, RetainedNodes, Variables, Substitutions, DebugPHIs, DebugInstructions, Numbered, Count };

Reason classify(const MachineFunction &MF) {
  const DISubprogram *SP = MF.getFunction().getSubprogram();
  if (!SP || !SP->getUnit() || SP->getUnit()->getEmissionKind() != DICompileUnit::LineTablesOnly)
    return OtherCU;
  if (!SP->getRetainedNodes().empty()) return RetainedNodes;
  if (!MF.getVariableDbgInfo().empty()) return Variables;
  if (!MF.DebugValueSubstitutions.empty()) return Substitutions;
  if (!MF.DebugPHIPositions.empty()) return DebugPHIs;
  for (const MachineBasicBlock &MBB : MF) {
    for (const MachineInstr &MI : MBB.instrs()) {
      if (MI.isDebugInstr()) return DebugInstructions;
      if (MI.peekDebugInstrNum()) return Numbered;
    }
  }
  return Empty;
}

class GuardLDV final : public MachineFunctionPass {
  MachineFunctionAnalysisManager Analyses;
  std::array<unsigned, Count> Reasons{};
  bool Omit = false;
public:
  static char ID;
  GuardLDV() : MachineFunctionPass(ID) {
    const char *Mode = std::getenv("OHM_LDV_GUARD");
    Omit = Mode && !std::strcmp(Mode, "guard");
  }
  ~GuardLDV() override {
    std::fprintf(stderr, "OHM_LDV_REASONS");
    for (unsigned N : Reasons) std::fprintf(stderr, " %u", N);
    std::fprintf(stderr, "\n");
  }
  void getAnalysisUsage(AnalysisUsage &AU) const override {
    AU.setPreservesCFG();
    AU.addRequired<TargetPassConfig>();
    MachineFunctionPass::getAnalysisUsage(AU);
  }
  bool runOnMachineFunction(MachineFunction &MF) override {
    bool Entry = getAnalysis<TargetPassConfig>().getTM<TargetMachine>().Options.ShouldEmitDebugEntryValues();
    Reason R = classify(MF);
    ++Reasons[R];
    if (R == Empty && Omit) return false;
    return !LiveDebugValuesPass(Entry).run(MF, Analyses).areAllPreserved();
  }
};

char GuardLDV::ID = 0;
RegisterPass<GuardLDV> Registration("ohm-guard-ldv-probe", "Probe variable-free live debug ranges", false, false);
RegisterTargetPassConfigCallback Configure([](TargetMachine &, PassManagerBase &, TargetPassConfig *Config) {
  const char *Mode = std::getenv("OHM_LDV_GUARD");
  if (!Mode || (std::strcmp(Mode, "original") && std::strcmp(Mode, "delegate") && std::strcmp(Mode, "guard"))) std::abort();
  auto *ID = &LiveDebugValuesID;
  auto Chosen = Config->getPassSubstitution(ID);
  if (!Chosen.isValid() || Chosen.isInstance() || Chosen.getID() != ID) std::abort();
  if (std::strcmp(Mode, "original")) Config->substitutePass(ID, &GuardLDV::ID);
  std::fprintf(stderr, "OHM_LDV_GUARD %s\n", Mode);
});
} // namespace
