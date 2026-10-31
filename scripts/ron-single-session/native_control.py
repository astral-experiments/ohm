"""Real unchanged proc-macro DSO changes tokens through an untracked external file."""
import hashlib
import json
from pathlib import Path
import subprocess


def run_control(place, evidence, env):
    place.mkdir()
    evidence.mkdir()
    (place / 'derive.rs').write_text('''extern crate proc_macro;
use std::fs::{self, OpenOptions};
use std::io::Write;
use proc_macro::TokenStream;
#[proc_macro_derive(Probe)]
pub fn derive(_: TokenStream) -> TokenStream {
    let input = fs::read_to_string("external.txt").unwrap();
    writeln!(OpenOptions::new().create(true).append(true).open("calls").unwrap(), "{input}").unwrap();
    format!("impl Item {{ fn answer() -> u32 {{ {input} }} }}").parse().unwrap()
}
''')
    (place / 'main.rs').write_text('''#[derive(probe::Probe)]
struct Item;
fn main() { println!("{}", Item::answer()); }
''')
    rust = ['rustc', '+ohm', '--edition=2024']
    subprocess.run([*rust, '--crate-type=proc-macro', '--crate-name=probe', 'derive.rs', '-o', 'libprobe.so'],
                   cwd=place, env=env, capture_output=True, check=True)
    dso = place / 'libprobe.so'
    ident = (dso.stat().st_dev, dso.stat().st_ino, hashlib.sha256(dso.read_bytes()).hexdigest())
    runs = []
    for i, value in enumerate(('17', '29', '"invalid"', '17')):
        (place / 'external.txt').write_text(value)
        paired = []
        for mode in ('warm', 'empty'):
            cache = place / ('ordinary-session' if mode == 'warm' else f'empty-session-{i}')
            if mode == 'empty': assert not cache.exists()
            old = (place / 'calls').read_bytes() if (place / 'calls').exists() else b''
            args = [*rust, '--crate-name=probe_consumer', 'main.rs', '--extern', 'probe=libprobe.so',
                    '--error-format=json', '-Ccodegen-units=1', f'-Cincremental={cache}', '-o', 'reader']
            p = subprocess.run(args, cwd=place, env=env, capture_output=True)
            tag = f'{i}-{mode}'
            (evidence / (tag+'.stderr')).write_bytes(p.stderr)
            assert (place / 'calls').read_bytes() == old + (value+'\n').encode()
            assert ident == (dso.stat().st_dev, dso.stat().st_ino, hashlib.sha256(dso.read_bytes()).hexdigest())
            ds = [json.loads(line) for line in p.stderr.splitlines()]
            if value.startswith('"'):
                errors = [d for d in ds if d.get('code') and d['level']=='error']
                assert p.returncode == 1 and len(errors)==1 and errors[0]['code']['code']=='E0308'
                assert any(s['is_primary'] and s['file_name']=='main.rs' for s in errors[0]['spans'])
                verdict = ds
            else:
                assert p.returncode == 0 and not ds
                out = subprocess.check_output([place/'reader'], cwd=place, env=env)
                assert out == (value+'\n').encode()
                verdict = out.decode().strip()
            paired.append(verdict)
            runs.append(dict(step=tag, argv=[str(a) for a in args], code=p.returncode, verdict=verdict))
        assert paired[0] == paired[1]
    result = dict(dso=list(ident), visits=runs, calls=(place/'calls').read_text().splitlines())
    (evidence/'terminal.json').write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
    return result
