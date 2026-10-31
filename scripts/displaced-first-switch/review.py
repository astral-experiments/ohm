"""Offline two-ZIP readback. Independent complete inflation, raw/encoded sizes, native image/roster ledger and actual double write."""
import gzip
import json
from pathlib import Path
import sys
import stat
import hashlib
import subprocess
import threading
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import tables as t

def native_body(z, desc):
    """Hash the entire archived native ELF without a temporary archive or output file."""
    h=hashlib.sha256();errors=[]
    member="native-bodies/"+desc["whole"]+".zst"
    with z.open(member) as f, subprocess.Popen(["zstd","-q","-d","-c"],stdin=subprocess.PIPE,stdout=subprocess.PIPE) as p:
        def feed():
            try:
                while b:=f.read(1<<20):p.stdin.write(b)
            except Exception as ex: errors.append(ex)
            finally:p.stdin.close()
        thread=threading.Thread(target=feed);thread.start()
        try:
            start=p.stdout.read(4);h.update(start);n=len(start)
            while b:=p.stdout.read(1<<20):
                n+=len(b);t.need(n<=512<<20,"unexpected native body size");h.update(b)
        finally:
            p.stdout.close();thread.join()
        t.need(not errors and p.wait()==0 and start==b"\x7fELF" and n==desc["size"] and h.hexdigest()==desc["whole"],"physical archived executable")

def read(receipts, streams):
    def obj(z,n): return json.loads(z.read(n))
    def compressed(z,n): return json.loads(gzip.decompress(z.read(n)))
    with zipfile.ZipFile(receipts) as r, zipfile.ZipFile(streams) as z:
        t.need(len(r.namelist())==len(set(r.namelist())) and len(z.namelist())==len(set(z.namelist())),"aliased archive names")
        end=obj(r,"complete.json"); rows=obj(r,"tables.json"); old=obj(r,'pre-switch-cold-source.json'); idx=obj(z,"streams.json")
        t.need(end['qualified'] and hashlib.sha256(z.read('streams.json')).hexdigest()==end['stream_index_sha256'] and len(idx)==80 and set(idx)|{'streams.json'}==set(z.namelist()),'different streams')
        rawledger=compressed(r,'cold-A/path-inodes.json.gz'); ledger=compressed(r,'first-B/path-inodes.json.gz')
        t.need(ledger==compressed(r,'post-shadow/path-inodes.json.gz') and t.sessions(rawledger).keys()==t.sessions(ledger).keys()==rows.keys()==old.keys(), "changed native corpus")
        shadow=compressed(r,'shadow-inodes.json.gz'); keys={tuple(v[:2]) for v in shadow.values()}; t.need(len(keys)==len(shadow)==61 and keys.isdisjoint(t.names(ledger)), 'one inode for each new node, no input aliases')
        identities=t.names(ledger);totals={k:{'original_A':0,'staged_A':0,'current_B':0} for k in t.KINDS}; sizes={}
        for unit,rec in rows.items():
            owner=old[unit]
            t.need({rec['A'],rec['B']}==set(t.sessions(ledger)[unit]) and rec['A']==owner['session'], 'wrong source ordinal')
            for k,s in rec['streams'].items():
                ar=s['raw'];bp=s['native_B'];ap=s['packed']; raw,aliases,_=t.table(rec['A'],k);_,_,bk=t.table(rec['B'],k)
                t.need(owner['tables'][k]==ar and ar['stat']==rawledger[raw]==ledger[raw] and identities[tuple(ledger[raw][:2])]==set(aliases[:2]) and ledger[raw][2]==2 and ar['allocated']==ledger[raw][4]*512, "source alias/raw size")
                t.need(bp['path']==bk and ledger[bk][2]==1 and bp['allocated']==ledger[bk][4]*512 and bp['reencoded']['sha256']==bp['actual_sha256'] and bp['reencoded']['bytes']==bp['bytes'], "current B calibration/alias")
                for side, expected, digest, size in [('A',[ar['bytes'],ar['sha256']],ap['sha256'],ap['bytes']),('B',bp['decoded'],bp['actual_sha256'],bp['bytes'])]:
                    name=side+'/'+Path(unit).name+'/'+k+'.zlib'
                    prefix=Path(rec[side]).name.rsplit('-',1)[0]
                    t.need(idx[name]==[size,digest] and z.getinfo(name).file_size==size and 0<size<=t.MAX_SIZE, "actual encoded stream")
                    with z.open(name) as f: t.need(hashlib.file_digest(f,'sha256').hexdigest()==digest, "stream hash")
                    with z.open(name) as f: t.decode(f,k,prefix,expected=expected)
                outrow=shadow[s['shadow']]
                t.need(outrow==ap['stat'] and outrow[2]==1 and stat.S_ISREG(outrow[3]) and outrow[5]==ap['bytes'] and outrow[4]*512==ap['allocated'] and 0<ap['allocated']<ar['allocated'], 'K physical eligibility')
                for column,v in [('original_A',ar['allocated']),('staged_A',ap['allocated']),('current_B',bp['allocated'])]:totals[k][column]+=v
        native_seen=set()
        for phase,count in [('empty-B',375),('cold-A',375),('first-B',20)]:
            visit=obj(r,phase+'/visit.json'); orig=compressed(r,phase+'/cargo.json.gz'); roster=compressed(r,phase+'/roster.json.gz');native=compressed(r,phase+'/native.json.gz')
            t.need(visit['dirty']==len(roster['dirty'])==count and len(roster['members'])==375 and orig['exit']==0 and orig['observer_argv'] is None and native['cli']['whole']==visit['cli'] and native['reader']['whole']==visit['reader'], 'source/physical CLI')
            typed="Expr="+("64" if phase=="cold-A" else "56")+" valid=1 rejected"
            t.need(native['typed']==typed and gzip.decompress(r.read(phase+"/reader-run.stdout.gz")).decode().strip()==typed,'actual typed Ruff layout')
            for key in ('cli','reader'):
                if native[key]['whole'] not in native_seen:
                    native_body(r,native[key]);native_seen.add(native[key]['whole'])
        t.need(end['cold']['cli']!=end['first']['cli']==end['empty']['cli'] and end['first']['reader']==end['empty']['reader'],'native branch equivalence')
        files={tuple(v[:2]):v[4]*512 for v in ledger.values()}; present=sum(files.values())
        originals=sum(v['original_A'] for v in totals.values()); packed=sum(v['staged_A'] for v in totals.values());peak=end['shadow_allocated']
        t.need(present==end['post_original']==end['first']['allocated'] and peak==sum(q[4]*512 for q in shadow.values()) and peak>=packed and int(end['du_coexistence'].splitlines()[-1].split()[0])==present+peak,'actual three-root coexistence')
        return dict(native_complete_images=len(native_seen),real_displaced_crates=len(rows),decoded_older=40,native_current=40,tables=totals,ordinary_first_B_allocated=present,raw_original=originals,tmp_encoded_payload=packed,observed_shadow_including_directories=peak,actual_all_staged_total=present+peak,conditional_settled_without_staging_dirs=present-originals+packed,conditional_total_reclaimed=originals-packed,conditional_largest_per_crate_staged_file_payload=max(sum(s['packed']['allocated'] for s in v['streams'].values()) for v in rows.values()),no_measured_product_change_or_within_Cargo_peak=True)
if __name__=='__main__': print(json.dumps(read(*map(Path,sys.argv[1:])),indent=2,sort_keys=True))
