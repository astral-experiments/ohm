"""Bind independent production distributions, real completed marginal/native prerequisites and the pre-existing cumulative plan."""
from hashlib import file_digest
from pathlib import Path
import json
def at(record,path):
    for key in path.split('.'):
        assert key.isidentifier();record=record[key]
    return record
def require(h,lock):
    j=lambda p:json.loads((h/p).read_bytes())
    def f(p):
        with (h/p).open('rb')as source:return file_digest(source,'sha256').hexdigest()
    expected={'derive/cumulative-material.json':'cumulative_material_sha256','derive/shared-native-material.json':'shared_production_native_sha256','derive/marginal-completed.json':'accepted_marginal_replay_sha256','derive/cumulative-source-native.json':'measured_source_native_sha256'}
    assert all(f(n)==lock[k] for n,k in expected.items());m=j('derive/cumulative-material.json');shared=j('derive/shared-native-material.json');recent=j('derive/marginal-completed.json');native=j('derive/cumulative-source-native.json')
    a,b=lock['roles'];lhs,rhs=[lock['arms'][r]for r in(a,b)];assert m['frozen_cumulative_sha256']==lock['measurement_plan_sha256']==f('measurement-plan.json') and m['native_production_migration']==f('derive/shared-native-material.json')
    assert m['services']=={a:lhs['service'],b:rhs['service']}and shared['roles']['S']['source']==lhs['source']and shared['roles']['F']['source']==rhs['source']
    assert shared['performance_measured']is False and set(shared['actual_both_directions']['roles'])=={'F-S','S-F'}and all([z['observed']for z in v]==['7','19','19']for v in shared['actual_both_directions']['roles'].values())
    assert shared['signed_cargo']==m['signed_release_cargo']and shared['actual_both_directions']['native_format_proofs']==native['genuine_migration']
    assert recent['all_native_gates_passed'] and recent['marginal_primary_qualified']is False and recent['outcome_family']=='prior marginal only'and recent['complete_pairs']==8 and recent['all_rustc_images']==128 and recent['unexpected_rustc_images']==0 and recent['zero_launch_controls']==8 and all(v==6 for v in recent['known_within_role_trajectories'])
    assert native['stock']['source']==lhs['source']['commit']and native['candidate']['commit']==rhs['source']['commit']and native['stock']['registered_foreign_transitions']==native['candidate']['foreign_transitions']==11
    assert len(lock['prior_boots'])==len({v['boot']for v in lock['prior_boots'].values()})
    if 'formal_linked_guard_sha256' in lock:
        assert f('derive/formal-build-guard.json')==lock['formal_linked_guard_sha256']
        build=j('derive/formal-build-guard.json');record=build['linked_measurement'];scope=build['compiled_cold_and_build_safeguards']
        assert record['run']==41442900507 and record['physical_job']==125268886206 and record['nonregression_gate']is True and record['repeatable_regression_observed'] is False and record['individual_below_1p10']==8
        assert scope['separate_formal_build_worker']['independent_verdict']==record and scope['explicit_governance'] and scope['actual_cold_visits']==8 and scope['ordinary_build_visits']==4 and not scope['registered_10pct_repeat_veto']
    for run,v in lock['prior_boots'].items():
        if 'additional_raw_sha256'not in v:continue
        name='derive/other-boot-'+run+'.json';raw=j(name);assert f(name)==v['additional_raw_sha256']and at(raw,v['native_boot_key'])==v['boot']and str(at(raw,v['native_run_key']))==run and at(raw,v['native_head_key'])==v['head']
