/// Private QA entry; the functions above are the byte-for-byte copied product functions.
pub(crate) fn local_optional_source_probe() {
    use crate::core::config::flags::Flags;
    let args: Vec<_> = std::env::args().skip(1).collect();
    let mut config = Config::parse(Flags::parse(&args));
    config.llvm_from_ci = true;
    config.src = PathBuf::from(std::env::var_os("OHM_QA_SOURCE").unwrap());
    config.out = PathBuf::from(std::env::var_os("OHM_QA_OUT").unwrap());
    let mode = std::env::var("OHM_QA_MODE").unwrap();
    if mode == "required" {
        config.download_file("https://qa.invalid/required", &config.out.join("required"), "required input unavailable");
        println!("QA_REQUIRED_COMPLETED");
    } else {
        let root = config.ci_llvm_root();
        match config.ohm_coalescer_sources(&root) {
            Some(path) => println!("QA_SOURCES={}", path.display()),
            None => println!("QA_SOURCES=NONE"),
        }
    }
}
