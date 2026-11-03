"""Ask the system elfutils reader to open the genuine .rodata on this exact ELF."""
from pathlib import Path
import ctypes as ct,os
def inspect(file,known_index):
    api=ct.CDLL('libelf.so.1');p=ct.c_void_p;z=ct.c_size_t
    for name,args,r in [('elf_version',[ct.c_uint],ct.c_uint),('elf_begin',[ct.c_int,ct.c_int,p],p),
                        ('elf_update',[p,ct.c_int],ct.c_longlong),('elf_getscn',[p,z],p),('elf_getdata',[p,p],p),('elf_errno',[],ct.c_int),
                        ('elf_errmsg',[ct.c_int],ct.c_char_p),('elf_end',[p],ct.c_int)]:
        f=getattr(api,name);f.argtypes=args;f.restype=r
    assert api.elf_version(1)==1;fd=os.open(file,os.O_RDONLY)
    try:
        e=api.elf_begin(fd,1,None);assert e;s=api.elf_getscn(e,known_index);assert s;api.elf_errno()
        d=api.elf_getdata(s,None);err=api.elf_errno();result={'readable':bool(d),'errno':err}
        if err:result['diagnostic']=api.elf_errmsg(err).decode()
        # ELF_C_NULL (0) computes layout and performs validation, without writing output.
        size=api.elf_update(e,0);error=api.elf_errno()
        result['elf_update_null']={'computed_size':size,'errno':error,'diagnostic':api.elf_errmsg(error).decode()if error else None}
        assert api.elf_end(e)==0;return result
    finally:os.close(fd)
