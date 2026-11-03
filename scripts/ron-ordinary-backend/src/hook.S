// Both signed SysV entry points have only pointer/integer arguments.
// Keep all argument registers, stack arguments and original return address.
.macro hook name
.text
.hidden \name\()_hook
.global \name\()_hook
.type \name\()_hook,@function
\name\()_hook:
    endbr64
    push %rax
    push %rdi
    push %rsi
    push %rdx
    push %rcx
    push %r8
    push %r9
    call inspect_\name
    test %eax,%eax
    pop %r9
    pop %r8
    pop %rcx
    pop %rdx
    pop %rsi
    pop %rdi
    pop %rax
    jne 1f
    jmp *\name\()_trampoline(%rip)
1:
    xor %eax,%eax
    ret
.size \name\()_hook, .-\name\()_hook
.endm
hook opt
hook emit
.section .note.GNU-stack,"",@progbits
