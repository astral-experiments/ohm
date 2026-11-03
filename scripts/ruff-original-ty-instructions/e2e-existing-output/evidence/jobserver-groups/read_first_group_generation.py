import sys,hashlib,json,gzip,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));from read_groups import group_rows;from read_relation import differences
def main():
    p=Path('groups-refused-original.zip');expected='00afcd62c17d513e93e237b27034f989ecbf9ba684ebe85a331e2b8d4436d7d5'
    with p.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None
        get=lambda n:json.loads(gzip.decompress(z.read(n))if n.endswith('.gz')else z.read(n))
        native,=[n for n in z.namelist()if n.startswith('old/native-')and n.endswith('.tsv.gz')]
        raw=gzip.decompress(z.read(native));group=group_rows(raw);assert group['threads']==1 and group['last_group_size']==8
        unit=get('old/inventory.json.gz');actual=unit['executables'][unit['binary']]['elf']['sha256'];assert len(unit['executables'])==102
        modes=('real-first','no-fds','tokens-0-1');e=[get('old-'+m+'-elf.json.gz')for m in modes];r=[get('old-'+m+'-role.json')for m in modes];assert e[0]['sha256']==e[2]['sha256']==actual and e[1]['sha256']!=actual
        assert set(s['sha256']for s in e)=={'6d3724468395065d8eb0721eac41893b01e38ffe69eeeb88a59419886ab7a893','f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2'}
        assert len({v['argv_sha256']for v in r})==1 and len({tuple(v['affinity'])for v in r})==1
        values=differences(e[0],e[1]);assert values['headers']==[['.rodata','sh_entsize',8,0]]and values['outside_section_byte_changes']==[[227975768,8,0]]and values['different_section_payloads']==['.note.gnu.build-id']
        assert r[0]['delivered'][0][1:4]==r[0]['delivered'][1][1:4]==[15,19034,4480]
        assert r[1]['delivered']==[[5,None],[7,None]]and r[0]['token_pre']==0 and r[2]['token_pre']==r[2]['token_post']==0
        assert r[0]['libelf']['elf_update_null']['computed_size']==r[2]['libelf']['elf_update_null']['computed_size']==-1 and r[1]['libelf']['elf_update_null']['computed_size']>0 and r[2]['elfutils_strip']['exit']==1
        orig=get('old-physical-original-descriptors.json');fo=get('old-409-live-inputs.json.gz')
        assert len(fo)==409 and orig['source_fds']==r[0]['delivered']
        b={'run':41712333191,'artifact':13269471484,'github_zip_sha256':expected,'source_sha':get('registration.json')['head'],'physical_native_elf':actual,'old_prior_genuine_reference':actual,'actual_file_count':len(fo),
           'actual_byte_count':sum(v[1][3]for v in fo),'acquired_original_pipe':orig['source_fds'],'same_raw_argv_sha256':r[0]['argv_sha256'],'field':values,'ordinary_group':group,
           'signed':{m:{k:v[k]for k in ('sha256','entsize','rodata_bytes','libelf','token_pre','token_post','delivered')}for m,v in zip(modes,r)},'native_elfutils_effect':r[2]['elfutils_strip'],
           'refusal':{'role':'tokens-1-2','tokens_before':1,'tokens_at_driver_return':0,'all_following_controls_unqualified':True}}
        Path('first-real-group-control.json').write_text(json.dumps(b,sort_keys=True,indent=2)+'\n')
if __name__=='__main__':main()
