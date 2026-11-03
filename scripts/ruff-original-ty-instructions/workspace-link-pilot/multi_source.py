"""Enable the proved fresh-output branch only on the first 48 registered Ruff roles."""
import json
from pathlib import Path
import prepare_reuse

HERE = Path(__file__).resolve().parent
E2E = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0"


def apply(src):
    files = prepare_reuse.apply(src)
    rep = prepare_reuse.base.rep
    lib, frozen, reuse = [src / "libwild/src" / n for n in ("lib.rs", "frozen.rs", "reuse.rs")]
    roles = json.loads((HERE / "accepted-48.json").read_bytes())
    assert len(roles) == len(set(roles)) == 48 and E2E in roles
    rep(frozen, "static ACTIVE:", "const ROLES: &[&str] = &[" + ",".join(map(json.dumps, sorted(roles))) + "];\nstatic ACTIVE:")
    rep(frozen, "s.ends_with(ROLE)", "ROLES.iter().any(|suffix| s.ends_with(*suffix))")
    with frozen.open("a") as f:
        f.write("""
pub(crate) fn generated_input() -> Option<PathBuf> {
    let mut names=std::env::args_os().map(PathBuf::from)
        .filter(|p|p.file_name().is_some_and(|n|n=="symbols.o"));
    let input=names.next()?;
    names.next().is_none().then_some(input)
}
pub(crate) fn fixture_output(path: &Path) -> bool {
    path.to_str().is_some_and(|s|s.ends_with(ROLE))
}
fn fixture_link() -> bool {
    let mut args=std::env::args_os();
    while let Some(arg)=args.next() {
        if arg=="-o" {return args.next().is_some_and(|out|fixture_output(Path::new(&out)));}
    }
    false
}
""")
    rep(lib, "let temp_root=std::env::args().nth(36).map(std::path::PathBuf::from);",
             "let temp_root=crate::frozen::generated_input();")
    old='    let Some(symbol)=args.get(36).and_then(|x|Path::new(x).parent()).and_then(|x|x.to_str())else{return};'
    rep(reuse, old, '    let tmp=crate::frozen::generated_input();\n    let Some(symbol)=tmp.as_deref().and_then(Path::parent).and_then(Path::to_str)else{return};')
    rep(frozen, '&& directory().join("mid-read").exists()', '&& directory().join("mid-read").exists() && fixture_link()')
    rep(frozen, '|| !directory().join("entry-wait").is_file()', '|| !directory().join("entry-wait").is_file() || !fixture_link()')
    rep(reuse, 'if state().join("mid-output").is_file()', 'if state().join("mid-output").is_file() && crate::frozen::fixture_output(output)')
    rep(reuse, 'if !state().join("exclusive-witness").exists()', 'if !state().join("exclusive-witness").exists() || !crate::frozen::fixture_output(path)')
    old='    if !attempt || !eligible'
    rep(reuse, old, '''    let Some(dev)=parts.next().and_then(|x|x.parse::<u64>().ok()) else{return Ok(None);};
    let Some(ino)=parts.next().and_then(|x|x.parse::<u64>().ok()) else{return Ok(None);};
'''+old)
    rep(reuse, '    if !before.is_file() || before.nlink()!=1',
        '    if before.dev()!=dev || before.ino()!=ino {log(format_args!("MISS\\toutput-donor-inode"));return Ok(None);}\n    if !before.is_file() || before.nlink()!=1')
    return files
