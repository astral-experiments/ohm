from pathlib import Path
import json,time,traceback
def run(t):
    sdk=t['sdk'];old_cargo=sdk.sdk/'bin/cargo';fixed=t['candidate'];upstream=t['official'];pub=t['pub'];root=t['root'];alias=t['alias'];producer=t['producer'];client=t['client'];old,new=t['cases']('private')
    out={};failed={};regular=(t['tgt'],t['shared'])
    for arm in ('stock','fixed','upgrade','stock-split','fixed-split','upstream-split','fixed-registry-build','upstream-registry-build'):
        rs={};out[arm]=rs;d=pub/'no-checksums'/arm
        try:
            is_reg=arm.endswith('registry-build')
            t['tgt'],t['shared']=regular if not is_reg else (Path(t['e']['CARGO_HOME'])/'registry/private-artifacts'/x for x in ('registry-target','registry-shared'))
            def environment():
                return {**t['e'],'RUSTFLAGS':'--remap-path-prefix=/ohm-unreachable-mtime=/also-unreachable','CARGO_TARGET_DIR':str(t['tgt']),'CARGO_BUILD_BUILD_DIR':str(t['shared'])}
            env=environment();subject=old_cargo if arm.startswith('stock')or arm=='upgrade' else fixed if arm.startswith('fixed') else upstream
            t['flip_link'](subject);t['evict']();producer.write_text(old);client.write_text(t['placeholder'])
            def phase(k,package='selected_client',historical=None):
                rs[k]=t['observe']('check',k,d/k,[],env,package,historical);return rs[k]
            found=phase('discover');body=t['client_source']
            if is_reg:
                actual=Path(found['metadata_path']);assert actual.is_relative_to(Path(env['CARGO_HOME'])/'registry')
                assert body.count('"../../selected.rmeta"')==1;body=body.replace('"../../selected.rmeta"',json.dumps(str(actual)))
            client.write_text(body);env.update(OLD_VALUE=str(found['fnv']),CHECK_VALUE='1')
            o=phase('old');phase('old-unchanged');time.sleep(1.08);producer.write_text(new)
            if arm.endswith('-split'):phase('producer-only','selected_producer')
            v=phase('edit');h=phase('next-unchanged')
            assert o['exit']==0 and v['rmeta']!=o['rmeta'] and v['rmeta']==h['rmeta']
            selected=[p for p in(d/'old').glob('raw-*.d')if ('libselected_producer-'if is_reg else'selected.rmeta')in p.read_text()]
            assert selected and any('# checksum:blake3='in p.read_text()for p in selected)==arm.startswith('fixed')
            if arm=='upgrade':
                assert v['exit']==h['exit']==0 and o['metadata_mtime_ns']==h['metadata_mtime_ns']
                history=(str(alias.readlink()),sdk.hf(alias));before=[(sdk.hf(p),p.stat().st_mtime_ns)for p in(producer,client)];t['flip_link'](fixed);u=phase('fixed-first-unchanged',historical=history)
                assert [(sdk.hf(p),p.stat().st_mtime_ns)for p in(producer,client)]==before
                assert u['errors']==['E0308']and 'selected_client'in u['rustc_execs'] and u['explicit_sha']==v['rmeta']
                # The new Cargo can select a new namespace. Keep the literal file itself in
                # place while using genuinely empty directories for the independent child.
                t['tgt'],t['shared']=root/'upgrade-empty-target',root/'upgrade-empty-shared';assert all(not p.exists()for p in(t['tgt'],t['shared']))
                env.update(CARGO_TARGET_DIR=str(t['tgt']),CARGO_BUILD_BUILD_DIR=str(t['shared']))
                c=phase('independent-clean',historical=history)
                assert c['errors']==u['errors'] and set(c['rustc_execs'])=={'selected_client','selected_producer'}and c['explicit_sha']==u['explicit_sha']
            else:
                t['evict']();c=phase('independent-clean');time.sleep(1.08);producer.write_text(old);p=phase('repair')
                assert c['errors']==['E0308']and c['exit']==101 and p['exit']==0 and c['rmeta']==v['rmeta']
                if arm.startswith(('upstream','fixed')):assert v['errors']==h['errors']==['E0308']and'selected_client'in v['rustc_execs']
                elif arm=='stock':assert v['exit']==h['exit']==0 and v['metadata_mtime_ns']==o['metadata_mtime_ns']and 'selected_client'not in v['rustc_execs']
        except Exception:
            failed[arm]=traceback.format_exc();print(failed[arm],flush=True)
        finally:
            t['tgt'],t['shared']=regular;sdk.put(pub/'no-checksum-results.json',out);sdk.put(pub/'no-checksum-failures.json',failed)
    return failed
