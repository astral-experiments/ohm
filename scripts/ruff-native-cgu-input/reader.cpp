// Research contact for a fully typed LLVM module. Existing filesystem caches are not opened.
#include "llvm/ADT/StringSet.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/Bitcode/BitcodeWriter.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/DebugProgramInstruction.h"
#include "llvm/IR/GlobalObject.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/Metadata.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/TrackingMDRef.h"
#include "llvm/IR/Verifier.h"
#include "llvm/IRReader/IRReader.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/SHA256.h"
#include "llvm/Support/SourceMgr.h"
#include "llvm/TargetParser/Triple.h"
#include "llvm/Transforms/Utils/Cloning.h"
#include "llvm-c/Transforms/PassBuilder.h"
#include <valgrind/callgrind.h>
#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace llvm { extern LLVM_ABI cl::opt<bool> PickMergedSourceLocations; }
using namespace llvm;
using File = std::pair<std::string, std::string>;

static void beginCount() {
  CALLGRIND_START_INSTRUMENTATION;
  CALLGRIND_ZERO_STATS;
  CALLGRIND_TOGGLE_COLLECT;
}
static void endCount() {
  CALLGRIND_TOGGLE_COLLECT;
  CALLGRIND_STOP_INSTRUMENTATION;
}
static std::string hash(StringRef Bytes) {
  return toHex(SHA256::hash(arrayRefFromStringRef(Bytes)), true);
}
static void uleb(std::string &Buffer, uint64_t Value) {
  do {
    uint8_t Byte = Value & 127;
    Value >>= 7;
    Buffer.push_back(Byte | (Value ? 128 : 0));
  } while (Value);
}
static void field(std::string &Buffer, StringRef S) {
  uleb(Buffer, S.size());
  Buffer.append(S.begin(), S.end());
}
static bool matchesAny(StringRef S, std::initializer_list<StringRef> Names) {
  return llvm::is_contained(Names, S);
}

// Verify the compiler mode independently of the input IR. The complete ordinary
// argv is also part of the comparison key, so target/codegen changes miss.
static std::string compilerMode(StringRef Bytes) {
  SmallVector<StringRef> AR;
  Bytes.split(AR, '\0', -1, false);
  StringSet<> C, Z, Single;
  bool Emit = false;
  for (size_t I=0; I<AR.size(); ++I) {
    StringRef V = AR[I];
    if (V.starts_with("@")) return "response-file";
    if (V=="--codegen" || V.starts_with("--codegen=") || V=="--unstable-options") return "unsupported-context-spelling";
    if (V.starts_with("--emit") && V!="--emit=dep-info,metadata,link") return "compiler-emit-mode";
    if (V == "--emit=dep-info,metadata,link") Emit = true;
    bool CG = V.starts_with("-C"), ZZ=V.starts_with("-Z");
    if (!CG && !ZZ) continue;
    if (V.size()==2) {
      if (++I>=AR.size()) return "missing-argument";
      V=AR[I];
    } else V=V.drop_front(2);
    StringRef K=V.split('=').first;
    if (CG) {
      if (matchesAny(K,{"opt-level","lto","embed-bitcode","debuginfo","debug-assertions","incremental"}) && !Single.insert(K).second) return "duplicate-codegen-option";
      if (!matchesAny(K,{"opt-level","lto","embed-bitcode","debuginfo","debug-assertions","metadata","extra-filename","incremental","linker-features","link-self-contained","link-arg"}))
        return ("compiler-context-" + K).str();
      C.insert(V);
    } else {
      if (!matchesAny(K,{"ohm-shared-stages","public-api-hash","threads","ohm-caller-local-cgus","ohm-stable-cgu-merging","ohm-incremental-mono-partitions","remap-cwd-prefix","ohm-early-metadata","checksum-hash-algorithm","ohm-check-relink-inputs"}))
        return ("compiler-context-" + K).str();
      Z.insert(V);
    }
  }
  for (StringRef R: {"opt-level=1","lto=off","embed-bitcode=no","debuginfo=line-tables-only","debug-assertions=on"})
    if (!C.contains(R)) return "compiler-profile";
  if (!Emit || !llvm::any_of(C,[](auto &KV){return KV.getKey().starts_with("incremental=");})) return "compiler-emit-mode";
  return {};
}
struct Placements {
  // In the representation the order/equality is shared across *all* files.
  // 0 and 1 are always reserved and can never become another physical line.
  std::set<unsigned> Lines = {0,1};
  std::map<unsigned,unsigned> Ranks;
  std::vector<unsigned> Original;
  std::map<File, std::set<unsigned>> FileLines;
  std::map<File, std::pair<unsigned,std::string>> Checks;
  static File id(DIFile *F) { return {F->getDirectory().str(),F->getFilename().str()}; }
  void line(DIFile *F,unsigned L) { if(F)FileLines[id(F)].insert(L); Lines.insert(L); }
  unsigned rank(unsigned L) const { return Ranks.at(L); }
  bool file(DIFile *F) {
    const auto C = F->getChecksum();
    if(C){unsigned Expected=C->Kind==DIFile::CSK_MD5?32:C->Kind==DIFile::CSK_SHA1?40:C->Kind==DIFile::CSK_SHA256?64:0; if(C->Value.size()!=Expected || !llvm::all_of(C->Value,[](char V){return isHexDigit(V);}))return false;}
    auto S = C ? std::make_pair(unsigned(C->Kind), C->Value.str()) : std::pair<unsigned,std::string>{0,""};
    auto Ent = Checks.emplace(id(F), S);
    return Ent.second || Ent.first->second == S;
  }
  void finish() {
    for(unsigned L : Lines) {Ranks.emplace(L,Original.size());Original.push_back(L);}
  }
  std::string encode() const {
    std::string B("CGU-GLOBAL-LINES\x01",17);
    uleb(B,Lines.size()); unsigned Last=0;
    for(unsigned L:Lines) { uleb(B,L-Last);Last=L; }
    uleb(B,Checks.size());
    for(auto &[F,C]:Checks) {
      field(B,F.first);field(B,F.second);uleb(B,C.first);field(B,C.second);
      auto I=FileLines.find(F); uleb(B,I==FileLines.end()?0:I->second.size());Last=0;
      if(I!=FileLines.end())for(unsigned L:I->second){unsigned R=rank(L);uleb(B,R-Last);Last=R;}
    }
    return B;
  }
};

struct Graph {
  std::vector<MDNode *> Nodes;
  DenseMap<MDNode *,unsigned> IDs;
  Placements P;
  std::string Why;

  void add(MDNode *N) {
    if(N && IDs.try_emplace(N,Nodes.size()).second)Nodes.push_back(N);
  }
  bool collect(Module &M) {
    if (M.getTargetTriple().str()!="x86_64-unknown-linux-gnu") return fail("target");
    if (!M.getModuleInlineAsm().empty()) return fail("module-asm");
    unsigned CUs=0;
    SmallVector<MDNode*,64> Ordinary;
    for(auto &N:M.named_metadata()) {
      if(!matchesAny(N.getName(),{"llvm.dbg.cu","llvm.module.flags","llvm.ident"}))return fail("unknown-named-metadata");
      for(MDNode *Op:N.operands()){add(Op);if(N.getName()!="llvm.dbg.cu")Ordinary.push_back(Op);}
    }
    SmallVector<Module::ModuleFlagEntry> Flags; M.getModuleFlagsMetadata(Flags);
    for(auto &V:Flags) {
      StringRef K=V.Key->getString();
      if(!matchesAny(K,{"CodeView","Dwarf Version","Debug Info Version","PIC Level","PIE Level","RtLibUseGOT","wchar_size","uwtable","frame-pointer","override-stack-alignment","MaxTLSAlign"}))
        return fail(("module-flag-"+K).str());
      if(K=="CodeView")return fail("codeview");
    }
    SmallVector<std::pair<unsigned,MDNode *>,8> Attached;
    for(auto &GO:M.global_objects()) {
      if(GO.getName().starts_with("__llvm_prf")||GO.getName().starts_with("__llvm_cov")||GO.getName().starts_with("__llvm_profile"))return fail("instrumentation-global");
      Attached.clear();GO.getAllMetadata(Attached);
      for(auto &A:Attached){add(A.second);if(A.first!=LLVMContext::MD_dbg)Ordinary.push_back(A.second);if(A.first==LLVMContext::MD_prof)return fail("function-profile-metadata");}
    }
    for(auto &F:M) {
      StringRef N=F.getName();
      if(N.starts_with("llvm.pseudoprobe") || N.starts_with("llvm.instrprof") || N.starts_with("__llvm_profile") || N.starts_with("__sanitizer") || N.starts_with("__asan_") || N.starts_with("__msan_") || N.starts_with("__tsan_") || N.starts_with("__ubsan_"))return fail("instrumentation-function");
      for(Attribute A:F.getAttributes().getFnAttrs()){
        std::string S=A.getAsString();StringRef V(S);
        if(V.contains("sanitiz") || V.contains("profile")||V.contains("sample")||V.contains("pseudo-probe") || V.contains("patchable-function")) return fail("instrumentation-attribute");
      }
      for(auto &B:F) {
        if(B.getTrailingDbgRecords() && !B.getTrailingDbgRecords()->empty())return fail("trailing-debug-record");
        for(auto &I:B) {
          if(I.hasDbgRecords())return fail("debug-record");
          if(auto *C=dyn_cast<CallBase>(&I); C && C->isInlineAsm())return fail("inline-asm");
          Attached.clear();I.getAllMetadata(Attached);for(auto &A:Attached){add(A.second);if(A.first!=LLVMContext::MD_dbg)Ordinary.push_back(A.second); if(A.first==LLVMContext::MD_prof){auto *Tag=A.second->getNumOperands()?dyn_cast_or_null<MDString>(A.second->getOperand(0)):nullptr;if(!Tag || Tag->getString()!="branch_weights")return fail("instruction-profile-metadata");}}
          for(Value *V:I.operands())if(auto *MV=dyn_cast<MetadataAsValue>(V))if(auto *NN=dyn_cast<MDNode>(MV->getMetadata())){add(NN);Ordinary.push_back(NN);}
        }
      }
    }
    SmallPtrSet<MDNode*,32> Visited;
    while(!Ordinary.empty()){auto *N=Ordinary.pop_back_val();if(!Visited.insert(N).second)continue;
      if(isa<DINode,DILocation>(N))return fail("debug-referenced-by-semantic-metadata");
      for(auto &O:N->operands())if(auto *K=dyn_cast_or_null<MDNode>(O.get()))Ordinary.push_back(K);}
    for(size_t I=0;I<Nodes.size();++I){
      MDNode *N=Nodes[I];
      if(N->isTemporary())return fail("unresolved-metadata");
      for(auto &O:N->operands())if(auto *M=dyn_cast_or_null<MDNode>(O.get()))add(M);
      if(auto *C=dyn_cast<DICompileUnit>(N)) {
        ++CUs;
        if(C->getEmissionKind()!=DICompileUnit::LineTablesOnly || C->getDebugInfoForProfiling() || !C->getSplitDebugFilename().empty() || C->getDWOId() || !C->getMacros().empty() || !C->getGlobalVariables().empty() || !C->getRetainedTypes().empty())return fail("custom-or-full-debug");
      }else if(auto *F=dyn_cast<DIFile>(N)){
        if(F->getSource().has_value())return fail("embedded-source");
        if(!P.file(F))return fail("ambiguous-file-checksum");
      }else if(auto *S=dyn_cast<DISubprogram>(N)){
        if(!S->getFile()||!S->getRetainedNodes().empty()||!S->getAnnotations().empty()||S->getKeyInstructionsEnabled())return fail("subprogram-debug-state");
        P.line(S->getFile(),S->getLine());P.line(S->getFile(),S->getScopeLine());
      }else if(auto *L=dyn_cast<DILocation>(N)){
        if(!L->getFile())return fail("fileless-location");
        P.line(L->getFile(),L->getLine());
      }else if(auto *L=dyn_cast<DILexicalBlock>(N)){
        if(!L->getFile())return fail("fileless-block");
        P.line(L->getFile(),L->getLine());
      }else if(!isa<MDTuple,DINamespace,DILexicalBlockFile,DISubroutineType>(N)){
        return fail("unsupported-metadata-kind");
      }
    }
    if(!CUs)return fail("missing-line-unit");
    P.finish();return true;
  }
  bool fail(std::string S) { Why=std::move(S);return false; }
  TempMDNode fresh(MDNode *N,const Placements *Recover) const {
    auto line=[&](unsigned V){return Recover ? Recover->Original.at(V) : P.rank(V);};
    auto &C=N->getContext();
    if(auto *F=dyn_cast<DIFile>(N)){
      auto Check=F->getChecksum();
      // The kind and absence are significant. The actual current bytes travel in placements.
      std::string Z;
      if(Check){if(Recover){auto &Exact=Recover->Checks.at(Placements::id(F));if(Exact.first!=unsigned(Check->Kind))report_fatal_error("checksum kind changed");Z=Exact.second;}else Z.assign(Check->Value.size(),'0');Check->Value=Z;}
      return DIFile::getTemporary(C,F->getFilename(),F->getDirectory(),Check,F->getSource());
    }
    if(auto *S=dyn_cast<DISubprogram>(N))return DISubprogram::getTemporary(C,S->getScope(),S->getName(),S->getLinkageName(),S->getFile(),line(S->getLine()),S->getType(),line(S->getScopeLine()),S->getContainingType(),S->getVirtualIndex(),S->getThisAdjustment(),S->getFlags(),S->getSPFlags(),S->getUnit(),S->getTemplateParams(),S->getDeclaration(),S->getRetainedNodes(),S->getThrownTypes(),S->getAnnotations(),S->getTargetFuncName(),S->getKeyInstructionsEnabled());
    if(auto *L=dyn_cast<DILocation>(N))return DILocation::getTemporary(C,line(L->getLine()),L->getColumn(),L->getScope(),L->getInlinedAt(),L->isImplicitCode(),L->getAtomGroup(),L->getAtomRank());
    if(auto *L=dyn_cast<DILexicalBlock>(N))return DILexicalBlock::getTemporary(C,L->getScope(),L->getFile(),line(L->getLine()),L->getColumn());
    return N->clone();
  }
  bool rewrite(Module &M,const Placements *Recover=nullptr) const {
    std::vector<TempMDNode> Temp;std::vector<TrackingMDNodeRef> New;
    Temp.reserve(Nodes.size());New.reserve(Nodes.size());
    for(auto *N:Nodes) {Temp.push_back(fresh(N,Recover));New.emplace_back(Temp.back().get());}
    for(auto &T:Temp) {
      for(unsigned I=0,E=T->getNumOperands();I<E;++I)
        if(auto *N=dyn_cast_or_null<MDNode>(T->getOperand(I))){auto P=IDs.find(N);if(P==IDs.end())return false;T->replaceOperandWith(I,New[P->second].get());}
    }
    for(unsigned I=0;I<Nodes.size();++I) {
      MDNode *N=Nodes[I]->isDistinct()?MDNode::replaceWithDistinct(std::move(Temp[I])):MDNode::replaceWithUniqued(std::move(Temp[I]));
      New[I].reset(N);
    }
    for(auto &N:New)if (!N->isResolved())N->resolveCycles();
    auto mapped=[&](MDNode *N)->MDNode*{auto Pos=IDs.find(N);if(Pos==IDs.end())report_fatal_error("unregistered metadata root");return New[Pos->second].get();};
    for(auto &N:M.named_metadata())for(unsigned I=0;I<N.getNumOperands();++I)N.setOperand(I,mapped(N.getOperand(I)));
    SmallVector<std::pair<unsigned,MDNode *>,8> A;
    for(auto &GO:M.global_objects()){A.clear();GO.getAllMetadata(A);GO.clearMetadata();for(auto &KV:A)GO.addMetadata(KV.first,*mapped(KV.second));}
    for(auto &F:M)for(auto &B:F)for(auto &I:B){
      A.clear();I.getAllMetadata(A);for(auto &KV:A)I.setMetadata(KV.first,mapped(KV.second));
      for(auto &O:I.operands())if(auto *V=dyn_cast<MetadataAsValue>(O.get()))if(auto *N=dyn_cast<MDNode>(V->getMetadata()))O.set(MetadataAsValue::get(M.getContext(),mapped(N)));
    }
    return !verifyModule(M,&errs());
  }
};

struct Receipt {
  std::string Reason, Placement, PlacementHash, ModuleHash, Key, Roundtrip, Original, Clone;
  uint64_t Bytes = 0, Lines = 0, Files = 0;
};

static std::string digest(const Module &M) {
  SmallVector<char,0> Buffer;
  raw_svector_ostream OS(Buffer);
  WriteBitcodeToFile(M,OS);
  return hash(StringRef(Buffer.data(),Buffer.size()));
}

// Isolate the literal non-overlapping cost centers in a real Callgrind graph.
#define COST __attribute__((noinline,disable_tail_calls))
extern "C" COST bool OHMInputEligibility(Module &Input, StringRef Flags, Receipt &R) {
  auto Mode=compilerMode(Flags);
  if(!Mode.empty())R.Reason=Mode;
  else if(PickMergedSourceLocations)R.Reason="pick-merged-source-locations";
  else {Graph Pre; if(!Pre.collect(Input)) R.Reason=Pre.Why;}
  return R.Reason.empty();
}
extern "C" COST void OHMCloneModule(const Module &Input, std::unique_ptr<Module> &M) {
  M=CloneModule(Input);
}
extern "C" COST bool OHMStockDeadArgAndGlobalDCE(Module &M) {
  auto Opts=LLVMCreatePassBuilderOptions();
  auto E=LLVMRunPasses(wrap(&M),"deadargelim,globaldce",nullptr,Opts);
  LLVMDisposePassBuilderOptions(Opts);
  if(!E)return true;
  char *Message=LLVMGetErrorMessage(E);
  errs()<<Message<<"\n";
  LLVMDisposeErrorMessage(Message);
  return false;
}
extern "C" COST void OHMDestroyScratch(std::unique_ptr<Module> &M) {
  M.reset();
}
extern "C" COST int OHMTypedBitcodeAndPlacements(Module *M, StringRef Flags,
                                                bool Check, Receipt &R) {
  if(Check)R.Roundtrip=digest(*M);
  Graph G;
  if(!G.collect(*M)){R.Reason=G.Why;return 0;}
  if(!G.rewrite(*M))return 7;
  SmallVector<char,0> Bitcode;
  raw_svector_ostream O(Bitcode);
  WriteBitcodeToFile(*M,O);
  R.ModuleHash=hash(StringRef(Bitcode.data(),Bitcode.size()));
  R.Placement=G.P.encode();
  R.PlacementHash=hash(R.Placement);
  R.Key=hash("native-ordinal-typed-1/"+hash(Flags)+"/"+R.ModuleHash);
  R.Bytes=Bitcode.size();R.Lines=G.P.Lines.size();R.Files=G.P.Checks.size();
  if(Check){
    Graph Back;
    if(!Back.collect(*M))return 11;
    if(!Back.rewrite(*M,&G.P))return 12;
    if(R.Roundtrip!=digest(*M)){errs()<<"roundtrip differs\n";return 13;}

  }
  return 0;
}

// Keep the ordinary owner intact. In particular the clone is paid even on a miss.
static int inspect(Module &Input, StringRef Flags, bool Check, Receipt &R) {
  if(!OHMInputEligibility(Input,Flags,R))return 0;
  if(Check)R.Original=digest(Input);
  std::unique_ptr<Module> M;
  OHMCloneModule(Input,M);
  if(Check)R.Clone=digest(*M);
  if(!OHMStockDeadArgAndGlobalDCE(*M))return 6;
  auto Status=OHMTypedBitcodeAndPlacements(M.get(),Flags,Check,R);
  OHMDestroyScratch(M);
  if(Check && R.Original!=digest(Input)){errs()<<"ordinary input mutated\n";return 14;}
  return Status;
}

int main(int argc,char **argv) {
  if(argc<4 || argc>6) {
    errs()<<"usage: reader CONTEXT.nul INPUT.bc {native|roundtrip|parse|policy|total} [PLACEMENTS] [pick-merged]\n"; return 2;
  }
  StringRef Phase=argv[3];
  if(!matchesAny(Phase,{"native","parse","policy","total","roundtrip"}))return 2;
  auto Context=MemoryBuffer::getFile(argv[1]);
  auto File=MemoryBuffer::getFile(argv[2]);
  if(!Context||!File)return 3;
  if(argc==6 && StringRef(argv[5])=="pick-merged") PickMergedSourceLocations=true;
  if(Phase=="total"||Phase=="parse")beginCount();
  auto C=std::make_unique<LLVMContext>();
  SMDiagnostic Diag;
  auto M=parseIR(MemoryBufferRef((*File)->getBuffer(),"input.bc"),Diag,*C);
  if(!M){Diag.print("reader",errs());return 4;}
  if(verifyModule(*M,&errs()))return 5;
  if(Phase=="parse")endCount();
  if(Phase=="policy")beginCount();
  Receipt R;
  auto Status=inspect(*M,(*Context)->getBuffer(),Phase=="roundtrip",R);
  if(Phase=="policy")endCount();
  M.reset();C.reset();
  if(Phase=="total")endCount();
  if(Status)return Status;
  if(!R.Reason.empty()){
    outs()<<json::Value(json::Object{{"status","fallback"},{"reason",R.Reason}})<<"\n";
    return 0;
  }
  if(argc>=5 && StringRef(argv[4])!="-"){
    std::error_code Err;raw_fd_ostream Stream(argv[4],Err,sys::fs::OF_None);
    if(Err)return 8;
    Stream<<R.Placement;
  }
  outs()<<json::Value(json::Object{{"status","eligible"},{"untouched_ordinary_module",R.Original},{"unmodified_clone",R.Clone},{"post_dae_roundtrip",R.Roundtrip},{"module_sha256",R.ModuleHash},{"complete_key",R.Key},{"placements_sha256",R.PlacementHash},{"placement_bytes",(int64_t)R.Placement.size()},{"canonical_bytes",(int64_t)R.Bytes},{"global_line_count",(int64_t)R.Lines},{"known_files",(int64_t)R.Files}})<<"\n";
}
