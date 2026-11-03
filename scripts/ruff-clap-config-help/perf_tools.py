"""Signed distribution perf and raw sampling, carried forward from Ohm 8147d4873296."""
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'ohm-clap-cli'
B = ROOT / 'diagnostic'
KITS = Path(__file__).resolve().parent
PERIOD = 8000009

def need(ok, why):
    if not ok:
        raise ValueError(why)

def save(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=1) + '\n')

def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()

def clean_subprocess():
    return {'HOME':str(ROOT/'home'), 'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'PYTHONHOME':'/usr', 'PYTHONNOUSERSITE':'1', 'PYTHONDONTWRITEBYTECODE':'1'}

def private_argv(path):
    libraries=ROOT/'perf-tools/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir() and Path(path).is_relative_to(ROOT/'perf-tools'):
        return ['/lib64/ld-linux-x86-64.so.2','--library-path',str(libraries),str(path)]
    return [str(path)]

def locate_perf():
    roots=[Path('/usr/lib'),ROOT/'perf-tools/usr/lib']
    candidates=[Path('/usr/bin/perf'),*(p for root in roots for pattern in ('linux-tools-*/perf','linux-tools/*/perf')for p in sorted(root.glob(pattern),reverse=True))]
    for path in candidates:
        if path.is_file():
            result=subprocess.run([*private_argv(path),'version','--build-options'],env=clean_subprocess(),capture_output=True)
            if result.returncode==0 and re.search(rb'libpython:\s*\[\s*on\s*\]',result.stdout):return path.resolve(),result.stdout.decode()
    return None,None

def prepare_perf():
    path,version=locate_perf();packages={}
    if path is None:
        # The base package contains the executable. The generic-flavour package supplies only a symlink.
        directory=ROOT/'perf-tools';directory.mkdir();perf_package='linux-tools-6.8.0-147=6.8.0-147.147'
        def extract(package,expected=None):
            known=set(directory.glob('*.deb'));subprocess.run(['apt-get','download',package],cwd=directory,check=True);deb,=set(directory.glob('*.deb'))-known;digest=sha(deb);need(expected is None or digest==expected,'wrong signed distribution package');subprocess.run(['dpkg-deb','-x',deb,directory],check=True);packages[deb.name]=digest
        digest='7bf31034e1914ff171c2b82c48e1f17b5123b7e63e1d4ef0582877c45cc17cd0'
        try:extract(perf_package,digest)
        except subprocess.CalledProcessError:
            subprocess.run(['sudo','-n','apt-get','-qq','update'],check=True,timeout=180);extract(perf_package,digest)
        real=directory/'usr/lib/linux-tools-6.8.0-147/perf';need(sha(real)=='2927eb0973fd937bdd417622531c95f1e6e19307a29c3e05a2c6198e12af6e56','different underlying distribution perf');ldd=subprocess.check_output(['ldd',real],text=True);(B/'perf-dynamic-libraries.txt').write_text(ldd)
        libraries={'libtraceevent.so.1':'libtraceevent1','libnuma.so.1':'libnuma1','libunwind.so.8':'libunwind8','libunwind-x86_64.so.8':'libunwind8','libslang.so.2':'libslang2','libpython3.12.so.1.0':'libpython3.12t64','libdw.so.1':'libdw1t64','libelf.so.1':'libelf1t64','libexpat.so.1':'libexpat1','libcap.so.2':'libcap2'}
        missing=re.findall(r'(\S+) => not found',ldd);need(set(missing)<=set(libraries),'unknown runtime dependency '+str(missing))
        for package in sorted({libraries[lib]for lib in missing}):extract(package)
        path,version=locate_perf()
    need(path is not None,'no usable distribution perf with its Python symbol reader')
    save(B/'perf-tool.json',dict(path=str(path),sha256=sha(path),version=version,packages=packages,hook=sha(KITS/'perf_hook.py'),event='instructions:u',period=PERIOD,clock='monotonic',callchain='frame pointers, 48 entries'))
    return path

def record(perf, out, command, period):
    return [*private_argv(perf),'record','--period','--no-buildid-cache','--clockid','mono','--call-graph','fp,48','-m','128','-e','instructions:u','-c',str(period),'-o',str(out), '--',*map(str,command)]

def decode(perf, source, case):
    env = clean_subprocess() | {'OHM_PERF_ROWS':str(case/'samples.ndjson.gz')}
    with (case/'symbolizer.stderr').open('wb') as err:
        subprocess.run([*private_argv(perf),'script','--no-demangle','-i',source,'-s',KITS/'perf_hook.py'],env=env,stdout=subprocess.DEVNULL,stderr=err,check=True,timeout=180)
    events=Counter()
    with (case/'raw-reader.stderr').open('wb')as e,subprocess.Popen([*private_argv(perf),'script','-D','-i',source],env=env,stdout=subprocess.PIPE,stderr=e)as proc:
        for line in proc.stdout:
            match=re.search(rb'\]: (PERF_RECORD_[A-Z_]+)',line)
            if match:events[match[1].decode()]+=1
        need(proc.wait(timeout=60)==0,'incomplete raw perf records')
    with (case/'event-header.txt').open('wb')as f:
        subprocess.run([*private_argv(perf),'report','--header-only','--stdio','-i',source],env=env,stdout=f,check=True)
    save(case/'record-counts.json',events)
    need(events['PERF_RECORD_SAMPLE']>0 and not any(events[k]for k in ('PERF_RECORD_LOST','PERF_RECORD_LOST_SAMPLES','PERF_RECORD_THROTTLE','PERF_RECORD_UNTHROTTLE')),'lost or throttled instruction samples')
    return events['PERF_RECORD_SAMPLE']

def sample_rows(case):
    frames,rows={},[]
    with gzip.open(case/'samples.ndjson.gz','rt')as src:
        for line in src:
            x=json.loads(line)
            if x[0]=='f':
                _,index,dso,symbol=x;need(index not in frames,'duplicate frame');frames[index]=(dso,symbol)
            else:
                mark,event,pid,tid,at,period,leaf,stack=x
                need(mark=='s' and event.startswith('instructions:u') and all(f[0]in frames for f in [leaf,*stack]),'different event or unknown symbol')
                rows.append((pid,tid,at,period,leaf,stack))
    return frames, rows
