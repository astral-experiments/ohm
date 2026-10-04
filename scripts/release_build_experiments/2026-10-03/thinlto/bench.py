#!/usr/bin/env python3
"""Paired release ThinLTO dependency-cache experiment on pinned CLI workspaces."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

ROOT = Path('/tmp/ohm-release-campaign/thinlto')
OUT = ROOT / 'results'
SHIMS = Path.home() / '.cargo/bin'
BOOT = Path('/tmp/codex-cargo-targets/ohm-rust/isolated/release-thinlto/bootstrap/x86_64-unknown-linux-gnu/stage1')
CONFIG = {
    'uv': ('46b84fd0bfec23b72f29e8e2185ba68a65052f48', 'crates/uv/src/bin/uv.rs'),
    'ruff': ('1df6db3e463ffa1b587dcf47f25360d40389b0f7', 'crates/ruff/src/main.rs'),
}

def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None

def machine():
    return {
        'cpuinfo': read('/proc/cpuinfo'), 'cgroup': read('/proc/self/cgroup'),
        'cpuset': read('/sys/fs/cgroup/cpuset.cpus.effective'),
        'cpu_max': read('/sys/fs/cgroup/cpu.max'),
        'memory_max': read('/sys/fs/cgroup/memory.max'),
        'cpu_count': os.cpu_count(), 'affinity': sorted(os.sched_getaffinity(0)),
        'compiler_config': read(ROOT / 'bootstrap.toml'),
        'compiler_version': subprocess.check_output([str(BOOT / 'bin/rustc'), '-Vv'], text=True),
        'timestamp': time.time(),
    }

class CpuMonitor(threading.Thread):
    def __init__(self, process_group):
        super().__init__(daemon=True)
        self.group = process_group
        self.stop_event = threading.Event()
        self.rows = []
    def sample(self):
        result = {}
        for process in Path('/proc').glob('[0-9]*'):
            try:
                text = (process/'stat').read_text()
                end = text.rfind(')')
                fields = text[end+2:].split()
                if int(fields[2]) == self.group or int(process.name) == os.getpid():
                    continue
                result[int(process.name)] = (int(fields[11])+int(fields[12]), text[text.find('(')+1:end])
            except (OSError, ValueError, IndexError):
                pass
        return result
    def run(self):
        previous = self.sample()
        old_time = time.monotonic()
        while not self.stop_event.wait(1):
            now = time.monotonic()
            current = self.sample()
            active = []
            outside_cpu = 0.0
            for pid, (ticks, name) in current.items():
                if pid in previous:
                    percent = 100*(ticks-previous[pid][0])/os.sysconf('SC_CLK_TCK')/(now-old_time)
                    outside_cpu += max(0, percent)
                    if percent >= 1:
                        active.append({'pid':pid, 'name':name, 'cpu_percent':percent})
            memory={fields[0]:int(fields[1]) for line in Path('/proc/meminfo').read_text().splitlines() if (fields:=line.split()) and fields[0] in ['MemAvailable:','SwapTotal:','SwapFree:']}
            self.rows.append({'elapsed':now-self.started, 'outside_cpu_percent':outside_cpu, 'active':sorted(active,key=lambda x:-x['cpu_percent'])[:12], 'memory_kib':memory,'memory_pressure':read('/proc/pressure/memory'),'io_pressure':read('/proc/pressure/io')})
            previous, old_time = current, now
    def start(self):
        self.started = time.monotonic()
        super().start()


def environment(repo, variant):
    env = os.environ.copy()
    for name in ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_LOG', 'RUSTC', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_BUILD_DIR', 'CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST', 'CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL', 'CARGO_BUILD_INCREMENTAL', 'CARGO_PROFILE_RELEASE_CODEGEN_UNITS', 'CARGO_PROFILE_RELEASE_OPT_LEVEL', 'CARGO_PROFILE_RELEASE_LTO', 'CARGO_PROFILE_RELEASE_INCREMENTAL', 'CARGO_BUILD_RUSTFLAGS']:
        env.pop(name, None)
    env.update({
        'PATH':str(SHIMS)+':'+env.get('PATH',''),
        'RUSTUP_HOME':str(ROOT/'rustup'),
        'CARGO_HOME':'/tmp/codex-cargo-home',
        'CARGO_TARGET_DIR':f'/tmp/codex-cargo-targets/{repo}/isolated/release-thinlto/final/{variant}',
        'CARGO_PROFILE_RELEASE_LTO':'thin',
        'CARGO_PROFILE_RELEASE_INCREMENTAL':'true',
        'RUSTFLAGS':'-Zohm-thin-lto-dependency-cache='+('yes' if variant=='on' else 'no'),
        'CARGO_NET_OFFLINE':'true',
    })
    if variant == 'fat':
        env.pop('CARGO_PROFILE_RELEASE_LTO', None)
        env.pop('CARGO_PROFILE_RELEASE_INCREMENTAL', None)
    return env


def wait_for_no_compilers():
    """Keep unrelated compiler activity out of the start of each timed build."""
    started=time.monotonic()
    quiet_since=None
    previous_cpu=[int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    idle_history=[]
    while True:
        active=[]
        for process in Path('/proc').glob('[0-9]*'):
            try:
                args=(process/'cmdline').read_bytes().split(b'\0')
                name=Path(os.fsdecode(args[0])).name if args else ''
                if name in ['rustc','cargo','clang','clang++','cc1','cc1plus','gcc','g++']:
                    active.append((process.name,name))
            except (OSError,ValueError):
                pass
        now=time.monotonic()
        current_cpu=[int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        delta=[now-old for old,now in zip(previous_cpu,current_cpu)]
        previous_cpu=current_cpu
        idle=100*(delta[3]+delta[4])/sum(delta) if sum(delta) else 100
        if active or idle<95:
            quiet_since=None
            idle_history=[]
        else:
            quiet_since=quiet_since or now
            idle_history.append(idle)
            if now-quiet_since>=5:
                return {'wait_s':now-started,'required_quiet_s':5,'required_idle_percent':95,'observed_min_idle_percent':min(idle_history)}
        if now-started>1800:
            raise RuntimeError('No compiler-free window after 30 minutes')
        time.sleep(1)

def compiler_overlap(row):
    return any(process['name'] in ['rustc','cargo','clang','clang++','cc1','cc1plus','gcc','g++']
               for sample in row['outside_cpu'] for process in sample['active'])


def build(repo, variant, phase, pair):
    quiet = wait_for_no_compilers()
    env = environment(repo,variant)
    cmd = [str(SHIMS/'cargo'), '+ohm', 'build', '--release', '--locked', '--verbose', '-p',repo,'--bin',repo]
    stem = f'{repo}-{phase}-{pair}-{variant}'
    with (OUT/(stem+'.log')).open('wb') as log:
        start = time.monotonic()
        proc = subprocess.Popen(cmd,cwd=ROOT/repo,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        monitor=CpuMonitor(proc.pid)
        monitor.start()
        _, status, usage = os.wait4(proc.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        proc.returncode = code
        elapsed=time.monotonic()-start
        monitor.stop_event.set()
        monitor.join()
    binary=Path(env['CARGO_TARGET_DIR'])/'release'/repo
    row={'repo':repo,'variant':variant,'phase':phase,'pair':pair,'elapsed_s':elapsed,'exit_code':code,'command':cmd,'env':{key:env.get(key) for key in ['RUSTFLAGS','RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','CARGO_PROFILE_RELEASE_LTO','CARGO_PROFILE_RELEASE_INCREMENTAL']},'outside_cpu':monitor.rows,'peak_rss_kib':usage.ru_maxrss,'user_cpu_s':usage.ru_utime,'system_cpu_s':usage.ru_stime,'preflight':quiet,'wall_start':time.time()-elapsed}
    if code == 0:
        row.update(size_bytes=binary.stat().st_size,sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (OUT/(stem+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps({key:row[key] for key in ['repo','variant','phase','pair','elapsed_s','exit_code']}),flush=True)
    if code:
        raise SystemExit(f'{stem} failed; see log')
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parser=argparse.ArgumentParser()
    parser.add_argument('repo',choices=CONFIG)
    args=parser.parse_args()
    repo=args.repo
    pin, main_rel=CONFIG[repo]
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT/repo,text=True).strip()
    assert actual==pin,(actual,pin)
    (OUT/(repo+'-machine.json')).write_text(json.dumps(machine(),indent=2)+'\n')
    main_path=ROOT/repo/main_rel
    original=subprocess.check_output(['git','show','HEAD:'+main_rel],cwd=ROOT/repo)
    marker=b'fn main() -> ExitCode {'
    assert original.count(marker)==1
    try:
        main_path.write_bytes(original)
        build(repo,'off','clean',0)
        build(repo,'on','clean',0)
        accepted=0
        accepted_by_order={0:0,1:0}
        acceptance=[]
        for pair in range(1,9):
            if accepted_by_order[pair%2]==2:
                continue
            edit=original.replace(marker,marker+b'\n    std::hint::black_box('+str(pair).encode()+b'u8);')
            main_path.write_bytes(edit)
            rows=[]
            for variant in (['off','on'] if pair%2 else ['on','off']):
                rows.append(build(repo,variant,'entry-edit',pair))
            overlap=any(compiler_overlap(row) or (sum(sample['outside_cpu_percent'] for sample in row['outside_cpu'])/max(1,len(row['outside_cpu'])) > 5*os.cpu_count()) for row in rows)
            acceptance.append({'pair':pair,'accepted':not overlap,'reason':'outside compiler or mean outside CPU above 5% of machine capacity' if overlap else 'no outside compiler; mean outside CPU at most 5% of machine capacity'})
            (OUT/(repo+'-pair-acceptance.json')).write_text(json.dumps(acceptance,indent=2)+'\n')
            if not overlap:
                accepted+=1
                accepted_by_order[pair%2]+=1
            if accepted==4:
                break
        if accepted<4:
            raise RuntimeError(f'Only {accepted} complete pairs had no outside compiler overlap')
        main_path.write_bytes(original)
        build(repo,'fat','clean-context',0)
        shutil.copy2(Path(environment(repo,'fat')['CARGO_TARGET_DIR'])/'release'/repo, OUT/(repo+'-fat-original'))
        main_path.write_bytes(original.replace(marker,marker+b'\n    std::hint::black_box(4u8);'))
        build(repo,'fat','entry-edit-context',0)
        for variant in ['off','on']:
            binary=Path(environment(repo,variant)['CARGO_TARGET_DIR'])/'release'/repo
            shutil.copy2(binary,OUT/(repo+'-'+variant))
        # Restoring the same original body in both variants also checks reversal.
        main_path.write_bytes(original)
        for variant in ['on','off']:
            build(repo,variant,'restore',0)
            binary=Path(environment(repo,variant)['CARGO_TARGET_DIR'])/'release'/repo
            shutil.copy2(binary,OUT/(repo+'-'+variant+'-original'))
    finally:
        main_path.write_bytes(original)

if __name__=='__main__':
    main()

