#[cfg(unix)]
fn pack_stream(
    path: &Path,
    source: impl Read,
    meta: &fs::Metadata,
    write_header: impl FnOnce(&mut dyn Write) -> io::Result<()>,
) -> io::Result<bool> {
    use std::os::unix::fs::MetadataExt;

    let file = File::create_new(path)?;
    let encode = || -> io::Result<bool> {
        let mut zip = ZlibEncoder::new(BufWriter::new(&file), Compression::fast());
        write_header(&mut zip)?;
        if io::copy(&mut source.take(meta.len() + 1), &mut zip)? != meta.len() {
            return Err(invalid());
        }
        zip.finish()?.flush()?;
        if file.metadata()?.blocks() >= meta.blocks() {
            return Ok(false);
        }
        file.set_permissions(meta.permissions())?;
        file.set_modified(meta.modified()?)?;
        Ok(true)
    };
    if matches!(encode(), Ok(true)) {
        Ok(true)
    } else {
        fs::remove_file(path)?;
        Ok(false)
    }
}
