.globl _start
.text
_start:
    mov $60,%rax
    mov $37,%edi
    syscall
.section .note.GNU-stack,"",@progbits
