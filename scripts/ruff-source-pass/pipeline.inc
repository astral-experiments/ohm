static RegisterPass<RegisterCoalescerLegacy> OhmSourcePass(
    "ohm-source-register-coalescer", "Source-built register coalescer", false, false);

// Install only where the target requested the standard pass. An already disabled
// or replaced pass belongs to the target.
static RegisterTargetPassConfigCallback InstallOhmCoalescer(
    [](TargetMachine &, PassManagerBase &, TargetPassConfig *Config) {
      const auto *Standard = &llvm::RegisterCoalescerID;
      auto Existing = Config->getPassSubstitution(Standard);
      if (!Existing.isValid() || Existing.isInstance() ||
          Existing.getID() != Standard)
        return;
      Config->substitutePass(Standard, &RegisterCoalescerLegacy::ID);
      OhmInstalls.fetch_add(1, std::memory_order_relaxed);
    });

extern "C" __attribute__((visibility("default"))) PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "ohm-native-register-coalescer", LLVM_VERSION_STRING,
          [](PassBuilder &) {}, nullptr};
}

