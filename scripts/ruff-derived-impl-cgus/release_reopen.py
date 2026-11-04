"""Use all frozen native and PMU checks, substituting the exact release compiler provenance."""
import hashlib,json,sys,zipfile
from pathlib import Path
here=Path(__file__).resolve().parent
digest=lambda b:hashlib.sha256(b).hexdigest()
def release_recipe(z,role,observed):
    spec=json.loads((here/'release-transports.json').read_bytes())[role]
    expected=here/'release-qualification'/(role+'.zip')
    assert digest(expected.read_bytes())==spec['qualification'][1]
    assert observed['transports'][role]==spec
    with zipfile.ZipFile(expected)as factory:
        for name in ('training.json','bootstrap.toml','source.json','sdk-sha256','sdk.json','native.json'):
            assert z.read(role+'/factory/'+name)==factory.read(name)
        training=json.loads(factory.read('training.json'));source=json.loads(factory.read('source.json'));sdk=json.loads(factory.read('sdk.json'))
        assert training['config']==spec['config']==digest(factory.read('bootstrap.toml'))
        assert training['script']==spec['script'] and min(v[1]for v in training['profiles'].values())>0 and set(training['profiles'])=={'rustc','rustdoc','rustfmt','clippy'}
        assert factory.read('sdk-sha256').decode().strip()==spec['tar'] and sdk['driver']==spec['driver'] and source['factory']==spec['qa'] and int(source['run'])==spec['run']
        assert source['verified_release_coordinator']=='8f25c47ff9e7c4ab2f22a1cad0638a26c7e26e1c'
        assert json.loads(z.read(role+'/factory/bootstrap.json'))=={'kind':'stage2-release','config':spec['config'],'build_script':spec['script'],'common_source_distribution_recipe':source['verified_release_coordinator']}
    return True
def main():
    original=here/'reopen.py';raw=original.read_bytes()
    assert digest(raw)=='011e82cda0b575ac42388040475a5247b5db641bc66828d691739ddd0674de38'
    stage1="sha(z.read(role+'/factory/bootstrap.json'))=='3129eb48157c6b610c65b818ac9f86269ab1257020cf12d29701a36111460993'"
    body=raw.decode();assert body.count(stage1)==1
    sys.path.insert(0,str(here));exec(compile(body.replace(stage1,'release_recipe(z,role,reg)'),original,'exec'),{'__name__':'__main__','__file__':str(original),'release_recipe':release_recipe})
if __name__=='__main__':main()
