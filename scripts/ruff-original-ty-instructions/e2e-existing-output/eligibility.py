"""Require precisely the argument grammar and pure input scripts used by the previously admitted native role."""
from pathlib import Path
import re
OPTIONS={1:'-plugin',2:'/usr/libexec/gcc/x86_64-linux-gnu/13/liblto_plugin.so',3:'-plugin-opt=/usr/libexec/gcc/x86_64-linux-gnu/13/lto-wrapper',
5:'--build-id',6:'--eh-frame-hdr',7:'-m',8:'elf_x86_64',9:'--hash-style=gnu',10:'--as-needed',11:'-dynamic-linker',12:'/lib64/ld-linux-x86-64.so.2',13:'-pie',14:'-z',15:'now',16:'-z',17:'relro',18:'-o',
176:'--as-needed',177:'-Bstatic',428:'-Bdynamic',429:'-lgcc_s',430:'-lutil',431:'-lrt',432:'-lpthread',433:'-lm',434:'-ldl',435:'-lc',436:'--eh-frame-hdr',437:'-z',438:'noexecstack',439:'--gc-sections',440:'-z',441:'relro',442:'-z',443:'now'}
def native_args(a):
    if len(a)!=446 or not all(a[i]==s for i,s in OPTIONS.items()):return False
    if not re.fullmatch(r'-plugin-opt=-fresolution=/tmp/cc[A-Za-z0-9]+\.res',a[4]):return False
    for i,x in enumerate(a):
        if i in OPTIONS or i==4:continue
        if i==0:
            if not x.endswith('/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'):return False
        elif i==19:
            if not x.endswith('/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0'):return False
        elif 23<=i<=35:
            if not x.startswith('-L/'):return False
        else:
            if not x.startswith('/') or not x.endswith(('.o','.rlib','.a')):return False
        if not x.isascii() or any(c.isspace()for c in x) or any(c in x for c in ('@','\0','?')):return False
    return True
