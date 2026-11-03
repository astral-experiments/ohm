"""Extend the existing stopped-exec census at its completed argv observation only."""
from pathlib import Path
import json,subprocess,sys
here=Path(__file__).resolve().parent
source,output,private,compiler=map(Path,sys.argv[1:])
text=source.read_text()
anchor='require(n==0 && total && close(fd)==0 && fclose(f)==0,"argv completed");'
assert text.count(anchor)==1
text=text.replace(anchor,anchor+'\n    capture_owner(task->tid,trigger);')
pos=text.index('struct task')
text=text[:pos]+'#include '+json.dumps(str(here/'capture.h'))+'\n'+text[pos:]
c=output.with_suffix('.c');c.write_text(text)
subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror','-DPRIVATE_ENV='+json.dumps(str(private)),'-DREAL_RUSTC='+json.dumps(str(compiler)),str(c),'-o',output],check=True)
