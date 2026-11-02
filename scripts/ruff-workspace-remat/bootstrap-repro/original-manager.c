#include <llvm-c/Analysis.h>
#include <llvm-c/Core.h>
#include <llvm-c/Target.h>
#include <llvm-c/TargetMachine.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
extern LLVMPassManagerRef LLVMRustCreateCoalescingPassManager(LLVMTargetMachineRef, bool);
int main(void) {
  if (LLVMInitializeNativeTarget()) return 1;
  char *triple = LLVMGetDefaultTargetTriple(), *error = NULL;
  LLVMTargetRef target;
  if (LLVMGetTargetFromTriple(triple, &target, &error)) return 2;
  LLVMTargetMachineRef machine = LLVMCreateTargetMachine(target, triple, "generic", "", LLVMCodeGenLevelDefault, LLVMRelocDefault, LLVMCodeModelDefault);
  if (!machine) return 3;
  LLVMContextRef context = LLVMContextCreate();
  LLVMModuleRef module = LLVMModuleCreateWithNameInContext("signed-stock-manager", context);
  LLVMTypeRef n = LLVMInt32TypeInContext(context);
  LLVMTypeRef ty = LLVMFunctionType(n, NULL, 0, false);
  LLVMValueRef f = LLVMAddFunction(module, "value", ty);
  LLVMBasicBlockRef b = LLVMAppendBasicBlockInContext(context, f, "entry");
  LLVMBuilderRef builder = LLVMCreateBuilderInContext(context);
  LLVMPositionBuilderAtEnd(builder, b);
  LLVMBuildRet(builder, LLVMConstInt(n, 2026, false));
  if (LLVMVerifyModule(module, LLVMReturnStatusAction, &error)) return 4;
  LLVMDisposeMessage(error);
  char *before = LLVMPrintModuleToString(module);
  for (int allow = 0; allow <= 1; ++allow) {
    LLVMPassManagerRef pm = LLVMRustCreateCoalescingPassManager(machine, allow);
    if (!pm || LLVMRunPassManager(pm, module)) return 5;
    LLVMDisposePassManager(pm);
  }
  char *after = LLVMPrintModuleToString(module);
  if (strcmp(before, after) || !strstr(after, "ret i32 2026")) return 6;
  printf("stock-manager: allow=false,true; changed=false; typed-return=i32 2026\n");
  LLVMDisposeMessage(before); LLVMDisposeMessage(after);
  LLVMDisposeBuilder(builder); LLVMDisposeModule(module); LLVMContextDispose(context);
  LLVMDisposeTargetMachine(machine); LLVMDisposeMessage(triple);
  return 0;
}
