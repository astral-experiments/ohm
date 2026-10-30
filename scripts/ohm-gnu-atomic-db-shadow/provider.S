/* A private constructor makes link-time selection observable before libtest starts. */
.text
.p2align 2
.type ohm_shadow_exit,%function
ohm_shadow_exit:
    mov x0, #EXIT_CODE
    mov x8, #94
    svc #0
    brk #0
.size ohm_shadow_exit, .-ohm_shadow_exit
.section .init_array,"aw",%init_array
.p2align 3
.xword ohm_shadow_exit
.section .note.GNU-stack,"",%progbits
