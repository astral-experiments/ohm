"""Run the existing whole uv_client compiler command in the isolated, preopened B history."""
from pathlib import Path
import json, os, subprocess, time, hashlib
h = Path(__file__).resolve().parent
out = Path('/tmp/evidence')
q = json.loads((out/'request.json').read_bytes())
ar = q['argv']
prefix = '/tmp/ohm-owner'
options = [q['valgrind'], '--tool=callgrind', '--trace-children=no', '--vgdb=full',
           '--vgdb-error=0', '--vgdb-prefix='+prefix, '--collect-jumps=no',
           '--log-file=/tmp/evidence/valgrind.log', '--callgrind-out-file=/tmp/evidence/raw.cg']
with (out/'rustc.stdout').open('xb') as so, (out/'rustc.stderr').open('xb') as se:
    proc = subprocess.Popen([*options,*ar],env={**os.environ,'VALGRIND_LIB':q['valgrind_lib']},
                            stdout=so,stderr=se)
    try:
        deadline = time.monotonic()+45
        while not list(Path('/tmp').glob('ohm-owner-from-vgdb-to-'+str(proc.pid)+'*')):
            assert proc.poll() is None and time.monotonic()<deadline
            time.sleep(.02)
        actual = Path(f'/proc/{proc.pid}/cmdline').read_bytes().split(b'\0')[:-1]
        exe = Path(f'/proc/{proc.pid}/exe')
        assert actual[-len(ar):] == list(map(os.fsencode,ar)) and exe.samefile(q['translator'])
        (out/'kernel.json').write_text(json.dumps({'child':proc.pid,'exe':str(exe.resolve()),
            'full_argv':[os.fsdecode(t) for t in actual],'unchanged_rustc_argv':len(ar)}))
        spec = {**q,'relative':True,'pid':proc.pid,'prefix':prefix,'outs':'/tmp/evidence'}
        (out/'vgdb.json').write_text(json.dumps(spec))
        denv = {**os.environ,'LD_LIBRARY_PATH':q['gdb_lib'],'CG_REQUEST':'/tmp/evidence/vgdb.json',
                'DEBUGINFOD_URLS':''}
        with (out/'gdb.stdout').open('xb') as gs, (out/'gdb.stderr').open('xb') as ge:
            g = subprocess.run([q['gdb'],'-nx','-nh','-batch','-q','-iex','set auto-load off',
                                '-ex','source '+str(h/'charge.py'),ar[0]],env=denv,stdout=gs,stderr=ge,timeout=1200)
        assert g.returncode == 0 and (out/'cost.json').is_file()
        assert proc.wait(timeout=120)==0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
