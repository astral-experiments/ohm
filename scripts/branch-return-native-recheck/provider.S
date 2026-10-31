.text
.type ohm_native_provider_exit_83,@function
ohm_native_provider_exit_83:
  mov $231,%eax
  mov $83,%edi
  syscall
  ud2
.section .preinit_array,"aw",@preinit_array
.quad ohm_native_provider_exit_83
.section .note.GNU-stack,"",@progbits
