"""Reopen both #27470 originals and compare their ordinary check and privacy verdicts."""
import argparse
from collections import Counter
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from zipfile import ZipFile

RUN = 41570685416
HEAD = '14b1043714c8685c0f337861a6f3af9aa929d03f'
DIGESTS = {
    'PC': 'd17e9dd0581e8c5f804e71b66b5822d0709c9b466af974ecf1cb167a856244b5',
    'CP': 'acdbeca012358eceed84691f69eab72e42e08720b0d645d17604dc8a5eead4ab',
}
STAGES = ('old', 'old-unchanged', 'edited', 'new-unchanged')
OWNERS = {'annotate_snippets', 'ruff_db', 'ruff_ranged_value', 'ty_combine', 'ty_ide',
          'ty_module_resolver', 'ty_project', 'ty_python_core', 'ty_python_semantic',
          'ty_server', 'ty_site_packages', 'ty_vendored'}
BINDING = json.loads((Path(__file__).resolve().parents[1]/'typed-factory-binding.json').read_bytes())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def file_digest(path):
    with path.open('rb') as data:
        return hashlib.file_digest(data, 'sha256').hexdigest()


def reader(directory):
    """Use the previously published Rust table schema and decoder by content hash."""
    source = directory/'rmeta.py'
    schema = directory/'compiler-schema.json'
    require(file_digest(source)=='471f1f074e05cfbfc574601bffc09d3015e879e653280a22dc79b481fad9d02a', 'reader')
    require(file_digest(schema)=='7fa0044e649b14fc56746d44b6d824a747fe4d2be447d4550a32f86b0e1c65f9', 'schema')
    spec = spec_from_file_location('qualified_rmeta', source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    parsed = json.loads(schema.read_bytes())
    return module.decode, parsed['symbols'], parsed['tables']


def member(z, key):
    return json.loads(z.read(key+'.json'))


def metadata(z, prefix, decode, symbols, tables):
    """Bind each of the twelve decoded rmetas to its recorded Cargo output path."""
    phase = member(z, prefix+'/phase')
    packed = z.read(prefix+'/witness-rmeta.tar.zst')
    require(hashlib.sha256(packed).hexdigest()==phase['witness_archive_sha'], 'metadata archive')
    block = subprocess.check_output(['zstd','-qdc'], input=packed)
    rows = {}
    with tarfile.open(fileobj=BytesIO(block)) as archive:
        for entry in archive:
            owner = Path(entry.name).stem
            require(owner in OWNERS and entry.name==owner+'.rmeta' and entry.isfile() and owner not in rows, 'witness member')
            body = archive.extractfile(entry).read()
            expected, = [digest for key,digest in phase['workspace_rmeta'].items() if key.split('/')[0]==owner]
            require(hashlib.sha256(body).hexdigest()==expected, 'workspace rmeta digest')
            root, _, public, _, _ = decode(body, symbols, tables, owner, 'rustc 1.99.0-dev (Ohm metadata 3)')
            rows[owner] = (root, public, len(body))
    require(rows.keys()==OWNERS, 'complete witness set')
    return rows


def privacy(z, role):
    """Demand the actual downstream E0616, its source text, and both successful transitions."""
    verdicts = []
    for name in ('public','private-warm','private-clean','public-repaired'):
        prefix = f'{role}/visibility-{name}'
        private = name.startswith('private')
        require(member(z,prefix+'/command')['exit']==(101 if private else 0), 'privacy exit code')
        events = [json.loads(line) for line in z.read(prefix+'/stdout').splitlines()]
        require([e['success'] for e in events if e['reason']=='build-finished']==[not private], 'final privacy verdict')
        errors = [e['message'] for e in events if e['reason']=='compiler-message' and e['message']['level']=='error']
        require(len(errors)==int(private), 'number of privacy errors')
        if private:
            error, = errors
            span, = [s for s in error['spans'] if s['is_primary']]
            require(error['code']['code']=='E0616' and span['file_name'].endswith('crates/ruff_db/src/diagnostic/mod.rs'), 'privacy error')
            require(any(s['text'].strip()=='let _ = &origin.path;' for s in span['text']), 'private field access')
            require(any(r['crate']=='ruff_db' for r in member(z,prefix+'/rustcs')), 'missing actual consumer')
            verdicts.append([error['code']['code'], error['message'], span['file_name'], span['line_start'], span['column_start']])
    require(verdicts[0]==verdicts[1], 'warm/empty privacy difference')
    return verdicts[0]


def role_result(z, role, schema):
    build = member(z, role+'/compiler')
    require(build['source']==BINDING['source'][role] and build['driver']==BINDING['driver'][role], 'compiler identity')
    counts = {}
    for name in STAGES:
        counter = member(z, f'{role}/{name}/pmu')
        require(counter['instructions']>0 and counter['enabled']==counter['running']>0 and counter['status']==0, 'incomplete counter')
        counts[name] = counter['instructions']
    edit = member(z,role+'/edited/phase')
    original = member(z,role+'/old/phase')
    empty = member(z,role+'/clean/phase')
    repaired = member(z,role+'/repair/phase')
    actual = member(z,role+'/edited/rustcs')
    require(Counter(row['crate'] for row in actual)==Counter({n:1 for n in OWNERS}), 'native work on edit')
    for row in actual:
        args = row['argv']
        require(args[args.index('--crate-name')+1]==row['crate'] and '--emit=dep-info,metadata' in args, 'native arguments')
    require(len(edit['inventory'])==279 and len(edit['workspace_rmeta'])==31, 'registered dependency graph')
    for name in ('old-unchanged','new-unchanged'):
        require(not member(z,f'{role}/{name}/rustcs'), 'unchanged check ran a compiler')
    require(edit['workspace_rmeta']==repaired['workspace_rmeta'], 'repair did not restore workspace outputs')
    require(all(q['inventory']==edit['inventory'] for q in (original,empty,repaired)), 'different Cargo units')
    require(all(q['diagnostics']==[] for q in (original,edit,empty,repaired)), 'successful check emitted diagnostics')
    require(any(d[1]=='E0308' for d in member(z,role+'/invalid/phase')['diagnostics']), 'missing type error')
    old = metadata(z,role+'/old',*schema)
    new = metadata(z,role+'/edited',*schema)
    delta = {}
    for name in sorted(OWNERS):
        a, prev, _ = old[name]
        b, curr, size = new[name]
        require(a['stable']==b['stable'], 'changed crate identity')
        delta[name] = {
            'public_hash_changed': a['public']!=b['public'],
            'global_hash_changed': a['global_hash']!=b['global_hash'],
            'changed_definition_rows': sum(prev[k]!=curr[k] for k in prev.keys()&curr.keys()),
            'rows_added':len(curr.keys()-prev.keys()), 'rows_removed':len(prev.keys()-curr.keys()),
            'edited_bytes':size,
        }
    return {'instructions':counts, 'privacy':privacy(z,role), 'edited_compilers':sorted(OWNERS),
            'empty_equal_files':sum(h==empty['workspace_rmeta'][n] for n,h in edit['workspace_rmeta'].items()),
            'definition_changes':delta}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives',type=Path)
    parser.add_argument('decoder_directory',type=Path)
    args = parser.parse_args()
    schema = reader(args.decoder_directory)
    result = {}
    for order,digest in DIGESTS.items():
        path = args.archives/f'{RUN}-{order}.zip'
        require(file_digest(path)==digest, 'original ZIP digest')
        with ZipFile(path) as z:
            worker = member(z,'worker')
            comparison = member(z,'comparison')
            require(worker['head']==comparison['head']==HEAD and worker['run']==RUN and comparison['order']==order, 'worker identity')
            require(worker['boot']==comparison['boot'], 'boot identity')
            result[order] = {'boot':worker['boot'],'job':worker['job'],'archive_sha256':digest}
            for role in 'PC':
                result[order][role] = role_result(z,role,schema)
            require(result[order]['P']['privacy']==result[order]['C']['privacy'], 'compiler privacy disagreement')
    require(result['PC']['boot']!=result['CP']['boot'], 'boots must be independent')
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=='__main__':
    main()
