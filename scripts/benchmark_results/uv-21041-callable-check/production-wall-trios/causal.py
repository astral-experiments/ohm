"""Join chronological Cargo events to actual direct externs; do not invent a release event."""
import json
from pathlib import Path

def analyze(raw, detail, commands, a=None, b=None):
    rows=list(map(json.loads,raw.splitlines()))
    units={r['index']:r for r in rows if r['reason']=='unit-registered'}
    launched={r['index'] for r in rows if r['reason']=='unit-started'}
    by_name={units[i]['target']['name']:i for i in launched}
    assert len(launched)==len(by_name)==len(commands)==8 and set(by_name)==set(detail['units'])
    externs={v[v.index('--crate-name')+1]:{v[i+1].split('=')[0]for i,t in enumerate(v)if t=='--extern'}for v in commands}
    output={}; times=detail['units']
    for name,i in by_name.items():
        state=times[name];inputs=sorted(units[k]['target']['name']for k in launched&set(units[i].get('dependencies',[])))
        assert set(inputs)==externs[name]&by_name.keys()
        metadata={n:times[n]['metadata'][0]['elapsed']for n in inputs}
        assert all(len(times[n]['metadata'])==1 for n in inputs)
        latest=max(metadata,key=metadata.get,default=None)
        overlap=sorted(n for n in inputs if times[n]['start']<=state['start']<times[n]['finish'])
        output[name]={'actual_direct_inputs':inputs,'still_active_on_start':overlap,'last_direct_metadata':latest,
                      'external_metadata_to_start_ms':(state['start']-metadata[latest])*1000 if latest else None,
                      'explicitly_unblocked_on_metadata':state['metadata'][0]['unblocked'],
                      'explicitly_unblocked_on_finish':state['finished_unblocked']}
        if a is not None:
            path=Path(a['relative_paths'][name+'@check']);assert Path(b['relative_paths'][name+'@check'])==path
            path=str(path.parent.parent/'fingerprint'/('lib-'+name+'.public-api-hash'))
            assert path in a['public_sidecars']and path in b['public_sidecars']
            output[name]['public_sidecar_changed']=a['public_sidecars'][path]!=b['public_sidecars'][path]
    end=max(t['finish'] for n,t in times.items()if n!='uv_client')
    assert abs(detail['terminal_only_tail_s']-(times['uv_client']['finish']-max(end,times['uv_client']['start'])))<1e-9
    return {'direct_edges_checked_against_actual_argv':sum(len(x['actual_direct_inputs']) for x in output.values()),
            'rmeta_before_producer_exit':sum(len(x['still_active_on_start'])for x in output.values()),
            'explicitly_attributed_unblocks':sum(len(x['explicitly_unblocked_on_metadata'])+len(x['explicitly_unblocked_on_finish'])for x in output.values()),
            'registered_units':len(units),'units':output,'last_other':max((n for n in times if n!='uv_client'),key=lambda n:times[n]['finish']),
            'terminal_exclusive_s':detail['terminal_only_tail_s'],'first_start_s':detail['first_started_s'],'last_finish_s':detail['last_finished_s'],
            'active_union_s':detail['unit_union_s'],'terminal_start':times['uv_client']['start'],'phases':detail['phases']}
