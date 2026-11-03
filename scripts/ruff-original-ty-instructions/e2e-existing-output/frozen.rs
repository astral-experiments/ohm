//! Freeze the exact bytes supplied to Wild for one diagnostic e2e link.
use std::fs::{File, OpenOptions};
use std::io::{self, Write as _};
use std::os::unix::fs::{FileExt as _, MetadataExt as _};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::sync::atomic::{AtomicU64, Ordering};

const ROLE: &str = "/ty_server/f5c6198f896cf7b0/out/e2e-f5c6198f896cf7b0";
static ACTIVE: OnceLock<bool> = OnceLock::new();
static SINK: OnceLock<Mutex<File>> = OnceLock::new();
static COPIED: AtomicU64 = AtomicU64::new(0);

pub(crate) fn active() -> bool {
    *ACTIVE.get_or_init(|| {
        let mut arguments = std::env::args_os();
        while let Some(value) = arguments.next() {
            if value == "-o" {
                return arguments.next().is_some_and(|name| {
                    let p = Path::new(&name);
                    p.starts_with(env!("WILD_QA_ROOT")) &&
                        p.to_str().is_some_and(|s| s.ends_with(ROLE))
                });
            }
        }
        false
    })
}

fn directory() -> PathBuf {
    Path::new(env!("WILD_QA_ROOT")).join("native-donor-state")
}

pub(crate) fn log(line: std::fmt::Arguments<'_>) {
    if !active() {
        return;
    }
    let file = SINK.get_or_init(|| {
        let file = directory().join(format!("actor-{}.tsv", std::process::id()));
        Mutex::new(OpenOptions::new().create_new(true).write(true).open(file).unwrap())
    });
    writeln!(file.lock().unwrap(), "{line}").unwrap();
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Stamp(u64, u64, u64, i64, i64);

pub(crate) fn stamp(meta: &std::fs::Metadata) -> Stamp {
    Stamp(meta.dev(), meta.ino(), meta.len(), meta.ctime(), meta.ctime_nsec())
}

pub(crate) fn snapshot(file: &File, path: &Path) -> io::Result<(Box<[u8]>, Stamp)> {
    let metadata = file.metadata()?;
    let len = metadata.len();
    if !metadata.is_file() || len > 400 << 20 || COPIED.fetch_add(len, Ordering::Relaxed) + len > 900 << 20 {
        return Err(io::Error::other("outside donor input bound"));
    }
    let before = stamp(&metadata);
    let mut data = vec![0u8;len as usize];
    let split = data.len() / 2;
    file.read_exact_at(&mut data[..split],0)?;
    if path.file_name().is_some_and(|p| p == "symbols.o") && directory().join("mid-read").exists() {
        let ready = directory().join("read-first-half");
        std::fs::write(&ready, path.as_os_str().as_encoded_bytes())?;
        let start = std::time::Instant::now();
        while !directory().join("continue-read").is_file() {
            if start.elapsed().as_secs() > 15 {
                return Err(io::Error::other("QA read gate timeout"));
            }
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    }
    file.read_exact_at(&mut data[split..],split as u64)?;
    if before != stamp(&file.metadata()?) || before != stamp(&std::fs::metadata(path)?) {
        log(format_args!("REFUSED\tchanged-during-read\t{}",path.display()));
        return Err(io::Error::other("file generation changed during the diagnostic copy"));
    }
    log(format_args!("FROZEN\t{}\t{}\t{}\t{}\t{}",metadata.dev(),metadata.ino(),
                     len,blake3::hash(&data),path.display()));
    Ok((data.into_boxed_slice(),before))
}

pub(crate) fn context() {
    for (i,arg) in std::env::args_os().enumerate() {
        log(format_args!("ARG\t{i}\t{arg:?}"));
    }
    let mut env: Vec<_> = std::env::vars_os().collect();
    env.sort();
    for (key,value) in env {
        log(format_args!("ENV\t{key:?}\t{}",blake3::hash(value.as_encoded_bytes())));
    }
    log(format_args!("CWD\t{:?}",std::env::current_dir().unwrap()));
}

pub(crate) fn entry_gate() -> io::Result<()> {
    if !active() || !directory().join("entry-wait").is_file() {
        return Ok(());
    }
    let mut symbols = std::env::args_os().map(PathBuf::from)
        .filter(|p| p.file_name().is_some_and(|s| s == "symbols.o"));
    let object = symbols.next().ok_or_else(|| io::Error::other("missing generated object"))?;
    if symbols.next().is_some() {
        return Err(io::Error::other("multiple generated objects"));
    }
    std::fs::write(directory().join("entry-ready"), object.as_os_str().as_encoded_bytes())?;
    let start=std::time::Instant::now();
    while !directory().join("entry-continue").is_file() {
        if start.elapsed().as_secs()>15 {
            return Err(io::Error::other("QA entry gate timeout"));
        }
        std::thread::sleep(std::time::Duration::from_millis(2));
    }
    Ok(())
}
