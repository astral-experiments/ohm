source_filename = "a.rs"
target triple = "x86_64-unknown-linux-gnu"

define i32 @probe(ptr %slot) !dbg !5 {
  store volatile i32 11, ptr %slot, align 4, !dbg !7
  store volatile i32 19, ptr %slot, align 4, !dbg !8
  %answer = load volatile i32, ptr %slot, align 4, !dbg !9
  ret i32 %answer, !dbg !10
}

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!11, !12}
!0 = distinct !DICompileUnit(language: DW_LANG_Rust, file: !1, producer: "source-coordinate check", isOptimized: true, runtimeVersion: 0, emissionKind: LineTablesOnly)
!1 = !DIFile(filename: "a.rs", directory: "/source")
!2 = !DIFile(filename: "b.rs", directory: "/source")
!3 = !{}
!4 = !DISubroutineType(types: !3)
!5 = distinct !DISubprogram(name: "probe", scope: !1, file: !1, line: 12, type: !4, scopeLine: 12, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0)
!6 = !DILexicalBlockFile(scope: !5, file: !2, discriminator: 0)
!7 = !DILocation(line: 70, column: 4, scope: !5)
!8 = !DILocation(line: B_LINE, column: 4, scope: !6)
!9 = !DILocation(line: 91, column: 4, scope: !5)
!10 = !DILocation(line: 92, column: 4, scope: !5)
!11 = !{i32 2, !"Dwarf Version", i32 4}
!12 = !{i32 2, !"Debug Info Version", i32 3}
