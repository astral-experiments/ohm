/// Private fixture invoking the actual caller copied verbatim inside this function.
pub(crate) fn qa() {
    let mut cfg = cc::Build::new();
    cfg.cpp(true)
        .target("x86_64-unknown-linux-gnu")
        .host("x86_64-unknown-linux-gnu")
        .opt_level(0)
        .debug(false)
        .cargo_metadata(false)
        .compiler("/usr/bin/g++");
    // REPLACE_WITH_PRODUCTION_CALL
    let tool = cfg.get_compiler();
    println!("QA_FLAGS={:?}", tool.args());
    if let Some(destination) = env::var_os("OHM_QA_FALLBACK_OBJECT") {
        let status = tool.to_command()
            .arg("-I").arg(env::var_os("OHM_QA_LLVM_INCLUDE").unwrap())
            .arg("-c").arg(env::var_os("OHM_QA_WRAPPER").unwrap())
            .arg("-o").arg(destination).status().unwrap();
        assert!(status.success());
    }
}
