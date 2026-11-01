
/// Diagnostic-only companion. The normal Eprintln child receives its original argv and environment.
fn observe_diesel(cmd: &std::process::Command, phase: &str, actor: u32, code: i32) {
    let mut watch = std::process::Command::new(std::env::var_os("OHM_DIESEL_PYTHON").unwrap());
    watch.arg("-IB").arg(std::env::var_os("OHM_DIESEL_OBSERVER").unwrap())
        .arg(phase).arg(std::process::id().to_string()).arg(actor.to_string()).arg(code.to_string())
        .arg(cmd.get_program()).args(cmd.get_args());
    for (name, value) in cmd.get_envs() {
        match value {
            Some(value) => { watch.env(name, value); }
            None => { watch.env_remove(name); }
        }
    }
    assert!(watch.status().expect("run Diesel observer").success());
}
