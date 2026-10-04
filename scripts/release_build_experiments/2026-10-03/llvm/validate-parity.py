"""Check real executable equality and the complete final fat-LTO pipeline."""
from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1])
a=(p/'flag-ruff').read_bytes();b=(p/'plugin-ruff').read_bytes();assert a==b
pipelines={};raw={}
for name in ['flag','plugin']:
 raw[name]=(p/f'{name}.stdout').read_bytes()
 lines=[line for line in raw[name].splitlines() if line.startswith(b'mergefunc,memprof-remove-attributes,cross-dso-cfi,')]
 assert len(lines)==1,(name,len(lines));assert len(lines[0])>1000
 pipelines[name]=lines[0]
assert pipelines['flag']==pipelines['plugin']
(p/'parity.json').write_text(json.dumps({'binary_sha256':hashlib.sha256(a).hexdigest(),'binary_bytes':len(a),'pass_trace_sha256':hashlib.sha256(pipelines['flag']).hexdigest(),'pass_trace_bytes':len(pipelines['flag']),'pass_trace_scope':'Only the complete final fat-LTO pipeline. Parallel prelink printing can interleave within lines; no whole stdout or prelink trace equality is claimed.','full_stdout_byte_identical':raw['flag']==raw['plugin']},indent=2)+'\n')
