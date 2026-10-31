// Unscored QA for the existing table codec; only the independent output path is new.
use std::fs::{self, File};
use std::io::{self, BufRead, BufReader, BufWriter, Read, Write};
use std::os::fd::FromRawFd;
use std::path::Path;
use flate2::{Compression, write::ZlibEncoder};

fn invalid() -> io::Error {
    io::ErrorKind::InvalidData.into()
}
include!("pack_stream.rs");

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let [descriptor, kind, aliases, session, output] = args.as_slice() else {
        return Err("expected an inherited read-only fd, G|Q, alias mask, session prefix, and new output".into());
    };
    let fd: i32 = descriptor.parse()?;
    let aliases: u8 = aliases.parse()?;
    if fd < 3 || !matches!(kind.as_str(), "G" | "Q") || aliases & 1 != 1 || aliases & !7 != 0
        || !session.starts_with("s-") || !session.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_')) {
        return Err(invalid().into());
    }
    // The parent lends an O_RDONLY|O_NOFOLLOW|O_NOATIME descriptor and waits for this child.
    let mut source = BufReader::new(unsafe { File::from_raw_fd(fd) });
    let meta = source.get_ref().metadata()?;
    if !meta.is_file() || !(64 << 10..=512 << 20).contains(&meta.len()) || !source.fill_buf()?.starts_with(b"RSIC") {
        return Err(invalid().into());
    }
    let written = pack_stream(Path::new(output), source, &meta, |zip| {
        zip.write_all(&[1, kind.as_bytes()[0], aliases])?;
        zip.write_all(&meta.len().to_le_bytes())?;
        zip.write_all(session.as_bytes())?;
        zip.write_all(&[0])
    })?;
    if !written {
        return Err("original K encoder declined this stream".into());
    }
    File::open(output)?.sync_all()?;
    Ok(())
}
