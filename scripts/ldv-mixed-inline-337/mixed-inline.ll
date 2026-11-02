source_filename = "ohm-mixed.c"
target triple = "x86_64-unknown-linux-gnu"

declare void @llvm.dbg.value(metadata, metadata, metadata)
declare i32 @opaque(i32)

define i32 @line_inline(i32 %x, i32 %cond) !dbg !8 {
entry:
  %witness = add i32 %x, 17, !dbg !16
  call void @llvm.dbg.value(metadata i32 %witness, metadata !13, metadata !DIExpression()), !dbg !16
  %test = icmp eq i32 %cond, 0, !dbg !16
  br i1 %test, label %left, label %right, !dbg !16
left:
  %a = call i32 @opaque(i32 %witness), !dbg !18
  br label %done, !dbg !18
right:
  %t = mul i32 %witness, 13, !dbg !19
  %b = call i32 @opaque(i32 %t), !dbg !19
  br label %done, !dbg !19
done:
  %q = phi i32 [%a, %left], [%b, %right]
  %answer = add i32 %q, %witness, !dbg !20
  ret i32 %answer, !dbg !20
}

define i32 @full_branch(i32 %x, i32 %cond) !dbg !21 {
entry:
  %witness = add i32 %x, 19, !dbg !23
  call void @llvm.dbg.value(metadata i32 %witness, metadata !22, metadata !DIExpression()), !dbg !23
  %test = icmp eq i32 %cond, 0, !dbg !23
  br i1 %test, label %left, label %right, !dbg !23
left:
  %a = call i32 @opaque(i32 %witness), !dbg !24
  br label %done, !dbg !24
right:
  %t = mul i32 %witness, 13, !dbg !25
  %b = call i32 @opaque(i32 %t), !dbg !25
  br label %done, !dbg !25
done:
  %q = phi i32 [%a, %left], [%b, %right]
  %answer = add i32 %q, %witness, !dbg !26
  ret i32 %answer, !dbg !26
}

define i32 @pure_line(i32 %x) !dbg !27 {
  %y = add i32 %x, 3, !dbg !28
  ret i32 %y, !dbg !28
}

!llvm.dbg.cu = !{!0, !2}
!llvm.module.flags = !{!30, !31}
!0 = distinct !DICompileUnit(language: DW_LANG_C99, file: !1, producer: "ohm", isOptimized: true, runtimeVersion: 0, emissionKind: LineTablesOnly)
!1 = !DIFile(filename: "line.c", directory: "/ohm")
!2 = distinct !DICompileUnit(language: DW_LANG_C99, file: !3, producer: "ohm", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug)
!3 = !DIFile(filename: "full.c", directory: "/ohm")
!4 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!5 = !DISubroutineType(types: !6)
!6 = !{!4, !4, !4}
!7 = !{}
!8 = distinct !DISubprogram(name: "line_inline", scope: !1, file: !1, line: 2, type: !5, scopeLine: 2, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !7)
!9 = distinct !DISubprogram(name: "full_inlined", scope: !3, file: !3, line: 32, type: !5, scopeLine: 32, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !2, retainedNodes: !10)
!10 = !{!13}
!13 = !DILocalVariable(name: "inline_witness", scope: !9, file: !3, line: 33, type: !4)
!15 = !DILocation(line: 3, column: 2, scope: !8)
!16 = !DILocation(line: 33, column: 4, scope: !9, inlinedAt: !15)
!18 = !DILocation(line: 34, column: 4, scope: !9, inlinedAt: !15)
!19 = !DILocation(line: 35, column: 4, scope: !9, inlinedAt: !15)
!20 = !DILocation(line: 36, column: 4, scope: !9, inlinedAt: !15)
!21 = distinct !DISubprogram(name: "full_branch", scope: !3, file: !3, line: 42, type: !5, scopeLine: 42, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !2, retainedNodes: !29)
!22 = !DILocalVariable(name: "full_witness", scope: !21, file: !3, line: 43, type: !4)
!23 = !DILocation(line: 43, column: 4, scope: !21)
!24 = !DILocation(line: 44, column: 4, scope: !21)
!25 = !DILocation(line: 45, column: 4, scope: !21)
!26 = !DILocation(line: 46, column: 4, scope: !21)
!27 = distinct !DISubprogram(name: "pure_line", scope: !1, file: !1, line: 52, type: !5, scopeLine: 52, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !7)
!28 = !DILocation(line: 53, column: 4, scope: !27)
!29 = !{!22}
!30 = !{i32 2, !"Dwarf Version", i32 5}
!31 = !{i32 2, !"Debug Info Version", i32 3}
