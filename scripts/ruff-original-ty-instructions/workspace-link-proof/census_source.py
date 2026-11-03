"""Observe each preregistered native role while always calling the stock full output writer."""

from pathlib import Path
import json
import prepare_reuse

HERE = Path(__file__).resolve().parent


def apply(src):
    files = prepare_reuse.apply(src)
    lib = src / "libwild/src/lib.rs"
    frozen = src / "libwild/src/frozen.rs"
    reuse = src / "libwild/src/reuse.rs"
    roles = sorted(json.loads((HERE / "roles.json").read_bytes()))
    assert len(roles) == 50
    rep = prepare_reuse.base.rep
    rep(
        frozen,
        'const ROLE: &str = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0";',
        "const ROLES: &[&str] = &[" + ",".join(json.dumps(r) for r in roles) + "];",
    )
    rep(frozen, "s.ends_with(ROLE)", "ROLES.iter().any(|suffix| s.ends_with(*suffix))")
    with frozen.open("a") as out:
        out.write("""
/// Locate the single membership-checked rustc temporary operand at its real position.
pub(crate) fn generated_input() -> Option<PathBuf> {
    let mut names = std::env::args_os().map(PathBuf::from)
        .filter(|p| p.file_name().is_some_and(|s| s == "symbols.o"));
    let input=names.next()?;
    names.next().is_none().then_some(input)
}
""")
    rep(
        lib,
        "let temp_root=std::env::args().nth(36).map(std::path::PathBuf::from);",
        "let temp_root=crate::frozen::generated_input();",
    )
    rep(
        reuse,
        "    let Some(symbol)=args.get(36).and_then(|x|Path::new(x).parent()).and_then(|x|x.to_str())else{return};",
        "    let temporary=crate::frozen::generated_input();\n    let Some(symbol)=temporary.as_deref().and_then(Path::parent).and_then(Path::to_str)else{return};",
    )
    original_write = (
        Path(prepare_reuse.__file__).with_name("fresh_output.inc").read_text().rstrip()
    )
    rep(lib, original_write, "            crate::reuse::request(args.output(),safe)?;")
    rep(
        reuse,
        "fn request(output: &Path, eligible: bool) -> std::io::Result<Option<(Vec<u8>,File)>>",
        "fn request(output: &Path, eligible: bool) -> std::io::Result<()>",
    )
    text = reuse.read_text()
    begin = text.index('    if !state().join("coordinate").is_file()')
    end = text.index("\npub(crate) fn normalized_environment()", begin)
    # Eliminate the complete data-returning branch. The sole result is always None.
    reuse.write_text(
        text[:begin]
        + """    let status=(|| -> std::io::Result<Option<(u64,u64,u64,u64,blake3::Hash)>> {
        let initial=std::fs::symlink_metadata(output)?;
        if !initial.is_file() || initial.nlink()!=1 || initial.mode()&0o111==0 ||
            !(1<<20..=250<<20).contains(&initial.len()) {return Ok(None);}
        let mut file=std::fs::OpenOptions::new().read(true)
            .custom_flags(libc::O_CLOEXEC|libc::O_NOFOLLOW|libc::O_NONBLOCK).open(output)?;
        let first=crate::frozen::stamp(&initial);
        if first!=crate::frozen::stamp(&file.metadata()?) {return Ok(None);}
        let mut hasher=blake3::Hasher::new();let mut total=0u64;let mut buffer=vec![0;1024*1024];
        loop {let n=file.read(&mut buffer)?;if n==0{break;} total+=n as u64;
            if total>initial.len(){return Ok(None);} hasher.update(&buffer[..n]);}
        if total!=initial.len() || first!=crate::frozen::stamp(&file.metadata()?) ||
            first!=crate::frozen::stamp(&std::fs::symlink_metadata(output)?) {return Ok(None);}
        Ok(Some((initial.dev(),initial.ino(),initial.nlink(),total,hasher.finalize())))
    })();
    match status {
        Ok(Some((dev,ino,nlink,n,digest)))=>log(format_args!("EXISTING\\t{dev}\\t{ino}\\t{nlink}\\t{n}\\t{digest}")),
        Ok(None)=>log(format_args!("EXISTING-REFUSED\\tattributes-or-change")),
        Err(e)=>log(format_args!("EXISTING-REFUSED\\tos-error\\t{}",e.raw_os_error().unwrap_or(-1))),
    }
    Ok(())
}
"""
        + text[end:]
    )
    signature = (
        "pub(crate) fn request(output: &Path, eligible: bool) -> std::io::Result<()>"
    )
    block = (
        reuse.read_text()
        .split(signature, 1)[1]
        .split("pub(crate) fn normalized_environment()", 1)[0]
    )
    assert (
        block.count("Ok(None)") >= 3
        and "Ok(Some((bytes,file)))" not in block
        and 'state().join("coordinate")' not in block
    )
    assert (
        "crate::reuse::start_fresh_creation" not in lib.read_text()
        and "FRESH-PUBLISH" not in lib.read_text()
    )
    return files
