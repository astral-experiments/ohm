use std::io::{self, BufRead, Write};
fn main() {
    let mut out=io::BufWriter::new(io::stdout().lock());
    for n in 0u32..=0x10ffff {
        let Some(c)=char::from_u32(n) else { continue };
        let Some(name)=unicode_names2::name(c) else { continue };
        let s=name.to_string();
        out.write_all(&[1]).unwrap();out.write_all(&n.to_le_bytes()).unwrap();
        out.write_all(&(s.len() as u32).to_le_bytes()).unwrap();out.write_all(s.as_bytes()).unwrap();
        out.write_all(&unicode_names2::character(&s).map(u32::from).unwrap_or(u32::MAX).to_le_bytes()).unwrap();
    }
    for line in io::stdin().lock().lines() {
        let s=line.unwrap();out.write_all(&[2]).unwrap();
        out.write_all(&(s.len() as u32).to_le_bytes()).unwrap();out.write_all(s.as_bytes()).unwrap();
        out.write_all(&unicode_names2::character(&s).map(u32::from).unwrap_or(u32::MAX).to_le_bytes()).unwrap();
    }
}
