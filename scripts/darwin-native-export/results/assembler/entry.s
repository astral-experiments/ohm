.text
.global _start
_start:
 mov $60,%eax
 mov $17,%edi
 syscall
.section .note.GNU-stack,"",@progbits
