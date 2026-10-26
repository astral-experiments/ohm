/* Static Linux x86-64. Each original thread has its own kernel lifetime and witness. */
.section .text
.globl _start
_start:
    mov 8(%rsp),%rax
    mov %rax,child_argv(%rip)
    mov 16(%rsp),%rsi
    movzbl (%rsi),%ebx
    mov 24(%rsp),%rsi
    movzbl (%rsi),%r12d
    sub $48,%r12d
    imul $1000000,%r12d,%r12d
    mov 32(%rsp),%rsi
    movzbl (%rsi),%r13d
    sub $48,%r13d
    imul $1000000,%r13d,%r13d
    mov $1,%edi
    cmp $120,%bl
    jne 1f
    mov $5,%edi
1:  call witness
    cmp $116,%bl
    je threads
    cmp $102,%bl
    je family
    cmp $101,%bl
    je exec_image
    cmp $107,%bl
    je group_exit
    cmp $114,%bl
    je copy
    cmp $113,%bl
    je search
    cmp $122,%bl
    je fault
    call loop
    jmp done
loop:
    mov %r12,%rcx
2:  add $1,%rax
    sub $1,%rcx
    jnz 2b
    ret
threads:
    mov $2,%r14d
    lea stack1_end(%rip),%rsi
    call spawn
    mov $3,%r14d
    lea stack2_end(%rip),%rsi
    call spawn
    call loop
    jmp done
spawn:
    mov $0x50f00,%edi
    xor %edx,%edx
    xor %r10d,%r10d
    xor %r8d,%r8d
    mov $56,%eax
    syscall
    test %rax,%rax
    js failed
    jz worker
    ret
worker:
    mov %r14,%rdi
    call witness
    cmp $107,%bl
    je sleeper
    call loop
    jmp done
family:
    call loop
    mov $57,%eax
    syscall
    test %rax,%rax
    js failed
    jz child
    mov %rax,%rdi
    lea status(%rip),%rsi
    xor %edx,%edx
    xor %r10d,%r10d
    mov $61,%eax
    syscall
    test %rax,%rax
    js failed
    cmpl $0,status(%rip)
    jne failed
    call loop
    jmp done
child:
    mov $4,%edi
    call witness
    mov %r13,%r12
    call loop
exec_image:
    mov child_argv(%rip),%rdi
    lea child_argv(%rip),%rsi
    xor %edx,%edx
    mov $59,%eax
    syscall
    jmp failed
copy:
    lea buf1(%rip),%rsi
    lea buf2(%rip),%rdi
    mov %r12,%rcx
    rep movsb
    jmp done
search:
    lea buf1(%rip),%rdi
    mov %r12,%rcx
    xor %eax,%eax
    repne scasb
    jmp done
fault:
    ud2
group_exit:
    lea pipe_fds(%rip),%rdi
    xor %esi,%esi
    mov $293,%eax
    syscall
    test %rax,%rax
    js failed
    mov $2,%r14d
    lea stack1_end(%rip),%rsi
    call spawn
    mov pipe_fds(%rip),%edi
    lea status(%rip),%rsi
    mov $1,%edx
    xor %eax,%eax
    syscall
    xor %edi,%edi
    mov $231,%eax
    syscall
sleeper:
    mov pipe_fds+4(%rip),%edi
    lea status(%rip),%rsi
    mov $1,%edx
    mov $1,%eax
    syscall
3:  mov $34,%eax
    syscall
    jmp 3b
done:
    xor %edi,%edi
    mov $60,%eax
    syscall
failed:
    mov $91,%edi
    mov $231,%eax
    syscall
witness:
    push %rdi
    mov $39,%eax
    syscall
    push %rax
    mov $186,%eax
    syscall
    push %rax
    mov $1,%edi
    mov %rsp,%rsi
    mov $24,%edx
    mov $1,%eax
    syscall
    add $24,%rsp
    ret
.section .rodata
exe: .asciz "/proc/self/exe"
mode_x: .asciz "x"
arg_one: .asciz "1"
.data
.align 8
child_argv: .quad exe,mode_x,arg_one,arg_one,0
.bss
.align 16
status: .space 8
pipe_fds: .space 8
buf1: .space 2000000
buf2: .space 2000000
stack1: .space 65536
stack1_end:
stack2: .space 65536
stack2_end:
.section .note.GNU-stack,"",@progbits
