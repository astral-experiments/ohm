source_filename = "candidate.rs"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare ptr @reserve_physical()
declare i64 @llvm.objectsize.i64.p0(ptr, i1 immarg, i1 immarg, i1 immarg)

define internal ptr @allocate(i64 %requested) noinline allocsize(0) !dbg !5 {
  %p = call ptr @reserve_physical(), !dbg !8
  ret ptr %p, !dbg !9
}

define i64 @observed() !dbg !6 {
  %p = call ptr @allocate(i64 REQUESTED) allocsize(0), !dbg !10
  %n = call i64 @llvm.objectsize.i64.p0(ptr %p, i1 false, i1 false, i1 false), !dbg !11
  ret i64 %n, !dbg !12
}

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!13, !14}
!0 = distinct !DICompileUnit(language: DW_LANG_Rust, file: !1, producer: "source-placement pass-order test", isOptimized: true, runtimeVersion: 0, emissionKind: LineTablesOnly)
!1 = !DIFile(filename: "candidate.rs", directory: "/source", checksumkind: CSK_MD5, checksum: "102030405060708090a0b0c0d0e0f000")
!3 = !{}
!4 = !DISubroutineType(types: !3)
!5 = distinct !DISubprogram(name: "allocate", scope: !1, file: !1, line: 3, type: !4, scopeLine: 3, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0)
!6 = distinct !DISubprogram(name: "observed", scope: !1, file: !1, line: 7, type: !4, scopeLine: 7, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0)
!8 = !DILocation(line: 4, column: 2, scope: !5)
!9 = !DILocation(line: 5, column: 2, scope: !5)
!10 = !DILocation(line: 8, column: 2, scope: !6)
!11 = !DILocation(line: 9, column: 2, scope: !6)
!12 = !DILocation(line: 10, column: 2, scope: !6)
!13 = !{i32 2, !"Dwarf Version", i32 4}
!14 = !{i32 2, !"Debug Info Version", i32 3}
