"""Exercise the native foreign trait on the measured metadata dependency path."""
import hashlib
import shutil

def verify(root, ws, state, origin, relay, producer, cargo, cmd, codes):
    view = ws / 'scope_view/src/main.rs'
    original = {file: file.read_bytes() for file in (origin, relay, view)}
    relay.write_text('''
pub fn count<T: ExactSizeIterator<Item = u8>>(mut iter: T) -> usize {
    let n = iter.len();
    assert_eq!(iter.by_ref().count(), n);
    n
}
pub fn observed() -> usize { count(scope_origin::example()) }
''')
    view.write_text('fn main() { println!("{}", scope_relay::observed()); }\n')

    def source(item, length, with_exact):
        exact = 'impl ExactSizeIterator for Counter { fn len(&self) -> usize { self.length } }'
        origin.write_text(producer() + f'''
pub struct Counter {{ length: usize }}
impl Iterator for Counter {{
    type Item = {item};
    fn next(&mut self) -> Option<Self::Item> {{
        if self.length == 0 {{ return None; }}
        self.length -= 1;
        Some(0)
    }}
    fn size_hint(&self) -> (usize, Option<usize>) {{ (self.length, Some(self.length)) }}
}}
{exact if with_exact else ''}
pub fn example() -> Counter {{ Counter {{ length: {length} }} }}
''')

    def behavior(value):
        cargo(['check', '-p', 'scope_view'])
        records = cargo(['build', '-p', 'scope_view'])
        path, = [r['executable'] for r in records if r['reason']=='compiler-artifact' and r['target']['name']=='scope_view' and r['executable']]
        output = cmd([path]).stdout
        if output != f'{value}\n'.encode():raise ValueError(('stale foreign trait',value,output))
        with open(path, 'rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return {'stdout': output.decode(), 'full_elf_sha256': digest}

    def warm_clean(label, value):
        warm = behavior(value)
        saved = root / ('prior-trait-' + label)
        if saved.exists() or not state.is_dir() or state.is_symlink():raise ValueError('unowned private fixture state')
        state.rename(saved)
        try:
            fresh = behavior(value)
            if warm != fresh:raise ValueError(('fresh foreign trait differs',label,warm,fresh))
        finally:
            if state.exists():shutil.rmtree(state)
            saved.rename(state)
        return warm

    def invalid(item, exact, expected):
        source(item, 19, exact)
        errors = codes(cargo(['check','-p','scope_view'],101))
        if expected not in errors:raise ValueError((expected,errors))
        return errors
    try:
        source('u8',11,True)
        old = warm_clean('old',11)
        missing = invalid('u8',False,'E0277')
        different = invalid('u16',True,'E0271')
        source('u8',19,True)
        repaired = warm_clean('repair',19)
        if old['full_elf_sha256']==repaired['full_elf_sha256']:raise ValueError('unchanged true native result')
        return {'old':old,'withdrawn_impl':missing,'changed_assoc_item':different,'repaired':repaired}
    finally:
        for path, contents in original.items():path.write_bytes(contents)
