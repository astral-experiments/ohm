//! Narrow single-link research gate. The private coordinator knows the receipt from the previous
//! full Cargo invocation. The program rereads both native inputs and the existing executable.
use std::fs::File;
use std::io::{Read as _, Write as _};
use std::os::unix::fs::{FileExt as _, MetadataExt as _, OpenOptionsExt as _};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

fn state() -> PathBuf {
    Path::new(env!("WILD_QA_ROOT")).join("native-donor-state")
}

fn notice(name: &str, bytes: &[u8]) -> std::io::Result<()> {
    let target = state().join(name);
    let staging = target.with_extension("pending");
    let mut f = File::create_new(&staging)?;
    f.write_all(bytes)?;
    drop(f);
    std::fs::rename(staging, target)
}

fn image() -> Option<String> {
    // No externally mutable code-generating DSO is eligible. The standalone GNU static
    // image is protected while running by normal Linux executable write exclusion.
    let maps = std::fs::read_to_string("/proc/self/maps").ok()?;
    let executable = std::fs::read_link("/proc/self/exe").ok()?;
    let mut image_code = false;
    for line in maps.lines() {
        let cols: Vec<_> = line.split_ascii_whitespace().collect();
        if cols.len() < 2 { return None; }
        if cols[1].contains('x') {
            if cols.len() != 6 { return None; }
            let name = cols[5];
            if name == "[vdso]" || name == "[vsyscall]" {continue;}
            if Path::new(name) != executable { return None; }
            image_code = true;
        }
    }
    if !image_code { return None; }
    let mut f=File::open("/proc/self/exe").ok()?;
    if f.metadata().ok()?.len() > 32<<20 {return None;}
    let mut hash=blake3::Hasher::new();
    let mut block=[0;32768];
    loop {
        let n=f.read(&mut block).ok()?;
        if n==0 {break;}
        hash.update(&block[..n]);
    }
    Some(hash.finalize().to_string())
}

pub(crate) fn request(output: &Path, eligible: bool) -> std::io::Result<Option<Vec<u8>>> {
    use crate::frozen::log;
    let image = image();
    let forbidden = std::env::vars_os().any(|(k,_)| k.to_str().is_none_or(|k| k.starts_with("WILD_") ||
        matches!(k,"LD_PRELOAD"|"LD_AUDIT"|"LD_DEBUG"|"LD_PROFILE"|"GLIBC_TUNABLES")));
    log(format_args!("ADMISSION\t{}\t{}",eligible && !forbidden,image.as_deref().unwrap_or("dynamic-or-unknown")));
    if !state().join("coordinate").is_file() {return Ok(None);}
    let id = std::process::id();
    if state().join("stock-reference").is_file() {
        use std::os::unix::fs::OpenOptionsExt as _;
        let path=state().join(format!("local-env-{id}"));
        let mut raw=std::fs::OpenOptions::new().create_new(true).write(true).mode(0o600).open(path)?;
        for (key,value) in std::env::vars_os() {
            raw.write_all(key.as_encoded_bytes())?;raw.write_all(b"=")?;
            raw.write_all(value.as_encoded_bytes())?;raw.write_all(b"\0")?;
        }
        drop(raw);
    }
    notice(&format!("ready-{id}"),b"complete\n")?;
    let response = state().join(format!("answer-{id}"));
    let deadline = Instant::now()+Duration::from_secs(120);
    while !response.is_file() {
        if Instant::now()>deadline {log(format_args!("MISS\tcoordinator-timeout"));return Ok(None);}
        std::thread::sleep(Duration::from_millis(2));
    }
    let action = std::fs::read_to_string(response)?;
    if action=="full\n" {log(format_args!("MISS\tcoordinator-full"));return Ok(None);}
    let mut parts=action.split_ascii_whitespace();
    let attempt=parts.next()==Some("verify");
    let expected=parts.next().and_then(|x|blake3::Hash::from_hex(x).ok());
    let Some(size)=parts.next().and_then(|x|x.parse::<usize>().ok()) else {return Ok(None);};
    if !attempt || !eligible || forbidden || image.is_none() || parts.next().is_some() ||
        expected.is_none() || size<1<<20 || size>250<<20 {log(format_args!("MISS\tconditions"));return Ok(None);}
    let started=Instant::now();
    let before=match std::fs::symlink_metadata(output) {Ok(x) => x, Err(_) => return Ok(None)};
    if !before.is_file() || before.nlink()!=1 || before.len()!=size as u64 || before.mode()&0o111==0 {
        log(format_args!("MISS\toutput-noncanonical"));return Ok(None);
    }
    let file=match std::fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK|libc::O_NOFOLLOW|libc::O_CLOEXEC).open(output){Ok(x)=>x,Err(_)=>return Ok(None)};
    let stamp=crate::frozen::stamp(&before);
    if stamp!=crate::frozen::stamp(&file.metadata()?) {log(format_args!("MISS\topen-generation"));return Ok(None);}
    let mut bytes=vec![0;size];
    let split=size/2;
    if file.read_exact_at(&mut bytes[..split],0).is_err() {log(format_args!("MISS\tshort-output"));return Ok(None);}
    if state().join("mid-output").is_file() {
        notice("output-half", output.as_os_str().as_encoded_bytes())?;
        let until=Instant::now()+Duration::from_secs(15);
        while !state().join("output-continue").is_file() {
            if Instant::now()>until{return Ok(None);}
            std::thread::sleep(Duration::from_millis(2));
        }
    }
    if file.read_exact_at(&mut bytes[split..],split as u64).is_err() ||
        Some(blake3::hash(&bytes))!=expected ||
        std::fs::symlink_metadata(output).ok().is_none_or(|m|stamp!=crate::frozen::stamp(&m)) ||
        stamp!=crate::frozen::stamp(&file.metadata()?) {
        log(format_args!("MISS\toutput-bytes-or-generation"));return Ok(None);
    }
    log(format_args!("ACCEPT\t{}\t{}\t{}\t{}\t{}",before.dev(),before.ino(),size,expected.unwrap(),started.elapsed().as_nanos()));
    Ok(Some(bytes))
}

pub(crate) fn normalized_environment() {
    // Keep all environment entries. Only canonicalize the two exact compiler nonce paths
    // in GCC's serialized argv, which Wild's native no-plugin branch does not interpret.
    let args:Vec<_>=std::env::args().collect();
    let Some(symbol)=args.get(36).and_then(|x|Path::new(x).parent()).and_then(|x|x.to_str())else{return};
    let Some(res)=args.get(4).and_then(|x|x.strip_prefix("-plugin-opt=-fresolution="))else{return};
    let mut names: Vec<_>=std::env::vars_os().collect();
    names.sort();
    for (name,value) in names {
        let n=name.to_str().unwrap_or("");
        let bytes=value.as_encoded_bytes();
        let normalized;
        let use_bytes=if n=="COLLECT_GCC_OPTIONS" {
            let Some(v)=value.to_str()else{return};
            normalized=v.replace(symbol,"<rustc-tmp>").replace(res,"<unused-lto-res>");
            normalized.as_bytes()
        }else{bytes};
        crate::frozen::log(format_args!("ENVKEY\t{name:?}\t{}",blake3::hash(use_bytes)));
    }
}
