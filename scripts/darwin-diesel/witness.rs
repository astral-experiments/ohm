
fn diesel_witness(cmd: &std::process::Command, phase: &str, code: i32) {
    let mut observe = std::process::Command::new(std::env::var_os("OHM_DIESEL_PYTHON").unwrap());
    observe.arg("-IB")
        .arg(std::env::var_os("OHM_DIESEL_OBSERVER").unwrap())
        .arg(phase)
        .arg(code.to_string())
        .arg(cmd.get_program())
        .args(cmd.get_args())
        .envs(cmd.get_envs().filter_map(|(k, v)| v.map(|v| (k, v))));
    assert!(observe.status().expect("start native graph witness").success());
}
