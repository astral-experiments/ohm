#![cfg(unix)]

use crate::prelude::*;
use cargo_test_support::{Execs, Project, basic_manifest, project, rustc_host, rustc_host_env};
use std::fs;
use std::path::{Path, PathBuf};
#[cfg(target_os = "linux")]
use std::process::Stdio;
#[cfg(any(target_os = "linux", target_os = "macos"))]
use std::time::{Duration, Instant};

// The slow compiler waits for a real test to run. This demonstrates overlap
// without asserting a wall-clock speedup or depending on compiler throughput.
fn wrapper() -> PathBuf {
    let p = project()
        .at("ready-wrapper")
        .file("Cargo.toml", &basic_manifest("ready-wrapper", "0.1.0"))
        .file(
            "src/main.rs",
            r#"
            use std::{env, fs, path::PathBuf, process::Command, thread,
                time::{Duration, Instant}};

            fn main() {
                let mut args = env::args_os().skip(1);
                let program = args.next().unwrap();
                let args: Vec<_> = args.collect();
                let slow = args.windows(2).any(|a| a[0] == "--crate-name" && a[1] == "z")
                    && args.iter().any(|a| a == "--test");
                let status = Command::new(program).args(args).status().unwrap();
                if slow {
                    if let Some(control) = env::var_os("READY_CONTROL") {
                        let control = PathBuf::from(control);
                        let mode = env::var("READY_MODE").unwrap();
                        fs::write(control.join("slow-active"), std::process::id().to_string()).unwrap();
                        if mode != "fallback" && mode != "terminal-fallback"
                            && mode != "terminal-pipeline" && mode != "terminal-redirected" {
                            let marker = if mode.starts_with("terminal") {
                                "release-build"
                            } else if mode == "build-failure" || mode == "signal" {
                                "active"
                            } else {
                                "a-timing"
                            };
                            let deadline = Instant::now() + Duration::from_secs(15);
                            while !control.join(marker).exists() {
                                assert!(Instant::now() < deadline, "ready test never started");
                                thread::sleep(Duration::from_millis(5));
                            }
                        }
                        if mode == "build-failure" || mode == "terminal-build-failure" {
                            eprintln!("intentional late compiler failure");
                            std::process::exit(1);
                        }
                        if mode == "signal" {
                            thread::sleep(Duration::from_secs(30));
                        }
                        fs::write(control.join("slow-finished"), "yes").unwrap();
                    }
                }
                std::process::exit(status.code().unwrap_or(1));
            }
            "#,
        )
        .build();
    p.cargo("-Zohm-defaults=no build")
        .masquerade_as_nightly_cargo(&["ohm-defaults"])
        .run();
    p.bin("ready-wrapper")
}

fn fixture() -> Project {
    project()
        .file(
            "Cargo.toml",
            "[workspace]\nmembers = [\"a\", \"z\"]\nresolver = \"3\"\n",
        )
        .file("a/Cargo.toml", &basic_manifest("a", "0.1.0"))
        .file("z/Cargo.toml", &basic_manifest("z", "0.1.0"))
        .file(
            "a/src/lib.rs",
            r#"
            #[test]
            fn selected() {
                use std::io::Write;
                let control = std::path::PathBuf::from(std::env::var_os("READY_CONTROL").unwrap());
                let mode = std::env::var("READY_MODE").unwrap();
                let mut runs = std::fs::OpenOptions::new().create(true).append(true)
                    .open(control.join("runs")).unwrap();
                writeln!(runs, "a").unwrap();
                std::fs::write(control.join("a-timing"),
                    if control.join("slow-finished").exists() { "after" } else { "during" }).unwrap();
                if mode == "test-failure" { panic!("intentional test failure"); }
                if mode == "runtime" {
                    assert_eq!(std::env::var("READY_VALUE").unwrap(), "new");
                    let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
                    assert_eq!(std::fs::read_to_string(out.join("value")).unwrap(), "new");
                }
                if mode == "build-failure" || mode == "signal" {
                    let child = std::process::Command::new("sleep").arg("30").spawn().unwrap();
                    std::fs::write(control.join("descendant"), child.id().to_string()).unwrap();
                    std::fs::write(control.join("active"), std::process::id().to_string()).unwrap();
                    std::thread::sleep(std::time::Duration::from_secs(30));
                }
                if mode.starts_with("terminal") {
                    unsafe extern "C" {
                        fn getpgrp() -> i32;
                        fn signal(signal: i32, handler: usize) -> usize;
                    }
                    if mode == "terminal-ignore-int" {
                        // SIGINT and SIG_IGN on the Linux/macOS PTY test hosts.
                        unsafe { signal(2, 1); }
                    }
                    let mut child = std::process::Command::new("sleep").arg("30").spawn().unwrap();
                    std::fs::write(control.join("descendant"), child.id().to_string()).unwrap();
                    std::fs::write(control.join("test-group"), unsafe { getpgrp() }.to_string()).unwrap();
                    std::fs::write(control.join("active-tmp"), std::process::id().to_string()).unwrap();
                    std::fs::rename(control.join("active-tmp"), control.join("active")).unwrap();
                    let mut input = String::new();
                    if mode == "terminal-pipeline" {
                        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(15);
                        while !control.join("input").exists() {
                            assert!(std::time::Instant::now() < deadline, "pipeline reader lost the terminal");
                            std::thread::sleep(std::time::Duration::from_millis(5));
                        }
                        input = std::fs::read_to_string(control.join("input")).unwrap();
                    } else if mode == "terminal-descendant-input" {
                        let stop = |name| std::env::var(name).unwrap().parse::<i32>().unwrap();
                        // The reader inherits ignored Ctrl-Z. Only its background read
                        // will request a tty stop after the shell resumes the job.
                        unsafe { signal(stop("READY_TSTP"), 1); }
                        let reader = std::process::Command::new("sh").arg("-c")
                            .arg(": > \"$READY_CONTROL/reader-ready\"\nIFS= read -r line || exit 1\nprintf '%s\\n' \"$line\"")
                            .stdout(std::process::Stdio::piped()).spawn().unwrap();
                        unsafe { signal(stop("READY_TTIN"), 1); }
                        std::fs::write(control.join("parent-ready"), "").unwrap();
                        let output = reader.wait_with_output().unwrap();
                        assert!(output.status.success());
                        input = String::from_utf8(output.stdout).unwrap();
                    } else if mode == "terminal-redirected" {
                        use std::io::BufRead;
                        let tty = std::fs::File::open("/dev/tty").unwrap();
                        std::io::BufReader::new(tty).read_line(&mut input).unwrap();
                    } else {
                        std::io::stdin().read_line(&mut input).unwrap();
                    }
                    assert_eq!(input, "hello\n");
                    std::fs::write(control.join("input"), input).unwrap();
                    child.kill().unwrap();
                    child.wait().unwrap();
                }
            }
            #[test]
            fn excluded() { panic!("the test filter was lost"); }
            "#,
        )
        .file("z/src/lib.rs", "#[test] fn selected() {}")
        .build()
}

fn command(p: &Project, wrapper: &Path, mode: &str) -> Execs {
    let mut cmd = p.cargo("test --workspace --lib -j2 -Zohm-defaults=no -Zohm-ready-tests");
    cmd.masquerade_as_nightly_cargo(&["ohm-defaults", "ohm-ready-tests"])
        .env("RUSTC_WRAPPER", wrapper)
        .env("READY_CONTROL", p.root().join("control"))
        .env("READY_MODE", mode);
    cmd
}

fn seed(p: &Project, wrapper: &Path) {
    fs::create_dir(p.root().join("control")).unwrap();
    command(p, wrapper, "fallback").arg("--no-run").run();
    assert!(!p.root().join("control/runs").exists());
}

fn change(p: &Project, revision: usize) {
    fs::remove_dir_all(p.root().join("control")).unwrap();
    fs::create_dir(p.root().join("control")).unwrap();
    p.change_file(
        "z/src/lib.rs",
        &format!(
            r#"#[test] fn selected() {{
                assert_eq!({revision}, {revision});
                if std::env::var("READY_MODE").unwrap().starts_with("terminal") {{
                    use std::os::fd::AsRawFd;
                    unsafe extern "C" {{ fn getpgrp() -> i32; fn tcgetpgrp(fd: i32) -> i32; }}
                    let tty = std::fs::File::open("/dev/tty").unwrap();
                    unsafe {{ assert_eq!(getpgrp(), tcgetpgrp(tty.as_raw_fd()), "later test lost the terminal"); }}
                }}
                std::fs::write(std::path::Path::new(&std::env::var("READY_CONTROL").unwrap())
                    .join("z-ran"), "yes").unwrap();
            }}"#
        ),
    );
}

fn assert_run(p: &Project, timing: &str) {
    assert_eq!(
        fs::read_to_string(p.root().join("control/runs")).unwrap(),
        "a\n"
    );
    assert_eq!(
        fs::read_to_string(p.root().join("control/a-timing")).unwrap(),
        timing
    );
}

#[cargo_test]
fn overlaps_fresh_tests_and_preserves_opt_out_and_fallbacks() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    for (revision, case) in ["enabled", "opt-out", "json", "runner", "target"]
        .iter()
        .enumerate()
    {
        change(&p, revision);
        let mut cmd = command(
            &p,
            &wrapper,
            if *case == "enabled" {
                "normal"
            } else {
                "fallback"
            },
        );
        match *case {
            "opt-out" => {
                cmd.arg("-Zohm-ready-tests=no");
            }
            "json" => {
                cmd.arg("--message-format=json");
            }
            "runner" => {
                cmd.env(
                    &format!("CARGO_TARGET_{}_RUNNER", rustc_host_env()),
                    &wrapper,
                );
            }
            "target" => {
                cmd.arg("--target").arg(rustc_host());
            }
            _ => {}
        }
        cmd.arg("--").arg("selected").run();
        assert_run(
            &p,
            if *case == "enabled" {
                "during"
            } else {
                "after"
            },
        );
        assert!(p.root().join("control/z-ran").exists());
    }
}

#[cargo_test]
fn early_failure_preserves_fail_fast_and_no_fail_fast() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    for (revision, no_fail_fast) in [false, true].iter().enumerate() {
        change(&p, revision);
        let mut cmd = command(&p, &wrapper, "test-failure");
        if *no_fail_fast {
            cmd.arg("--no-fail-fast");
        }
        cmd.arg("--")
            .arg("selected")
            .with_status(101)
            .with_stdout_contains("[..]intentional test failure[..]")
            .run();
        assert_run(&p, "during");
        assert_eq!(p.root().join("control/z-ran").exists(), *no_fail_fast);
    }
}

#[cargo_test]
fn uses_current_runtime_inputs_and_ignores_disabled_binaries() {
    let wrapper = wrapper();
    let p = fixture();
    p.change_file("a/Cargo.toml", &format!(
        "{}\n[features]\noptional=[]\n[[bin]]\nname=\"a\"\npath=\"src/main.rs\"\n[[bin]]\nname=\"disabled\"\npath=\"src/disabled.rs\"\nrequired-features=[\"optional\"]\n",
        basic_manifest("a", "0.1.0")
    ));
    p.change_file(
        "a/src/disabled.rs",
        "compile_error!(\"disabled binary must not be built\");",
    );
    p.change_file("a/src/main.rs", "fn main() { print!(\"old\"); }");
    p.change_file("a/build.rs", "fn main() {}");
    p.change_file(
        "a/tests/runtime.rs",
        r#"
        #[test] fn selected() {
            let output = std::process::Command::new(env!("CARGO_BIN_EXE_a")).output().unwrap();
            assert!(output.status.success());
            assert_eq!(output.stdout, b"new");
            std::fs::write(std::path::Path::new(&std::env::var("READY_CONTROL").unwrap())
                .join("current-binary"), "yes").unwrap();
        }
    "#,
    );
    fs::create_dir(p.root().join("control")).unwrap();
    command(&p, &wrapper, "fallback")
        .arg("--tests")
        .arg("--no-run")
        .run();
    assert!(!p.root().join("control/runs").exists());
    p.change_file("a/src/main.rs", "fn main() { print!(\"new\"); }");
    p.change_file("a/build.rs", r#"fn main() {
        println!("cargo::rustc-env=READY_VALUE=new");
        std::fs::write(std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).join("value"), "new").unwrap();
    }"#);
    change(&p, 1);
    command(&p, &wrapper, "runtime")
        .arg("--tests")
        .arg("--")
        .arg("selected")
        .run();
    assert_run(&p, "during");
    assert!(p.root().join("control/current-binary").exists());
}

#[cfg(target_os = "linux")]
fn process_state(pid: i32) -> Option<char> {
    match fs::read_to_string(format!("/proc/{pid}/stat")) {
        Ok(stat) => stat.rsplit_once(") ").unwrap().1.chars().next(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => panic!("failed to inspect process {pid}: {error}"),
    }
}

#[cfg(target_os = "linux")]
fn assert_process_tree_stopped(p: &Project) {
    let deadline = Instant::now() + Duration::from_secs(5);
    for name in ["active", "descendant", "slow-active", "test-group"] {
        if matches!(name, "slow-active" | "test-group")
            && !p.root().join("control").join(name).exists()
        {
            continue;
        }
        let pid = fs::read_to_string(p.root().join("control").join(name))
            .unwrap()
            .parse()
            .unwrap();
        // The shell can report Cargo's exit before a killed descendant exits.
        while !matches!(process_state(pid), None | Some('Z')) {
            assert!(
                Instant::now() < deadline,
                "{name} process {pid} is still running"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

#[cargo_test]
#[cfg(target_os = "linux")]
fn build_failure_cancels_the_active_test_and_descendants() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    change(&p, 1);
    command(&p, &wrapper, "build-failure")
        .arg("--")
        .arg("selected")
        .with_status(101)
        .with_stderr_contains("[..]intentional late compiler failure[..]")
        .run();
    assert_run(&p, "during");
    assert_process_tree_stopped(&p);
}

#[cargo_test]
#[cfg(target_os = "linux")]
fn interrupt_cancels_the_active_test_and_descendants() {
    use std::os::unix::process::{CommandExt, ExitStatusExt};

    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    change(&p, 1);
    let mut cmd = command(&p, &wrapper, "signal");
    cmd.arg("--").arg("selected");
    let mut child = cmd
        .build_command()
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(fs::File::create(p.root().join("signal.log")).unwrap())
        .process_group(0)
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(15);
    while !p.root().join("control/active").exists() {
        assert!(
            child.try_wait().unwrap().is_none() && Instant::now() < deadline,
            "test did not start: {}",
            fs::read_to_string(p.root().join("signal.log")).unwrap()
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    // SAFETY: this is the isolated process group created for the test command.
    assert_eq!(unsafe { libc::kill(-(child.id() as i32), libc::SIGINT) }, 0);
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break status;
        }
        assert!(
            Instant::now() < deadline,
            "Cargo did not handle interruption"
        );
        std::thread::sleep(Duration::from_millis(5));
    };
    assert!(status.signal() == Some(libc::SIGINT) || status.code() == Some(130));
    assert_process_tree_stopped(&p);
}

// Exercise the actual terminal driver and an interactive shell's job table.
// Sending signals directly to Cargo cannot establish foreground/input behavior.
#[cfg(any(target_os = "linux", target_os = "macos"))]
struct TerminalSession {
    shell: std::process::Child,
    master: fs::File,
    control: PathBuf,
    output: String,
    cursor: usize,
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
impl TerminalSession {
    fn new(p: &Project, cmd: &mut Execs) -> Self {
        use std::os::fd::{AsRawFd, FromRawFd};
        use std::os::unix::process::CommandExt;

        let (mut master, mut slave) = (-1, -1);
        // SAFETY: openpty initializes both descriptors; File takes ownership.
        let (master, slave) = unsafe {
            assert_eq!(
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                ),
                0
            );
            libc::fcntl(master, libc::F_SETFD, libc::FD_CLOEXEC);
            libc::fcntl(slave, libc::F_SETFD, libc::FD_CLOEXEC);
            (fs::File::from_raw_fd(master), fs::File::from_raw_fd(slave))
        };
        let cargo = cmd.build_command();
        let mut shell = std::process::Command::new("bash");
        shell
            .args(["--noprofile", "--norc", "-i"])
            .current_dir(p.root())
            .stdin(slave.try_clone().unwrap())
            .stdout(slave.try_clone().unwrap())
            .stderr(slave);
        for (key, value) in cargo.get_envs() {
            if let Some(value) = value {
                shell.env(key, value);
            } else {
                shell.env_remove(key);
            }
        }
        shell
            .env("PS1", "READY-SHELL> ")
            .env("TERM", "dumb")
            .env("HISTFILE", "/dev/null")
            .env_remove("PROMPT_COMMAND");
        // SAFETY: only async-signal-safe calls between fork and exec. The slave
        // is already stdin; the shell starts a new session with a controlling tty.
        unsafe {
            shell.pre_exec(|| {
                if libc::setsid() < 0 || libc::ioctl(0, libc::TIOCSCTTY as _, 0) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut terminal = Self {
            shell: shell.spawn().unwrap(),
            master,
            control: p.root().join("control"),
            output: String::new(),
            cursor: 0,
        };
        terminal.expect("READY-SHELL> ");
        terminal.send(b"set -b\n");
        terminal.expect("READY-SHELL> ");
        // The master reports the terminal foreground group, not our test runner's.
        assert_eq!(
            unsafe { libc::tcgetpgrp(terminal.master.as_raw_fd()) },
            terminal.shell.id() as i32
        );
        terminal
    }

    fn start(&mut self, cmd: &mut Execs, suffix: Option<&str>) {
        fn quote(value: &std::ffi::OsStr) -> String {
            format!("'{}'", value.to_str().unwrap().replace('\'', "'\\''"))
        }
        let cargo = cmd.build_command();
        // exec preserves the shell job's PID/group while recording it for cleanup.
        let mut line = format!(
            "sh -c 'echo $$ > \"$1\"; shift; exec \"$@\"' sh {} {}",
            quote(self.control.join("cargo-pid").as_os_str()),
            quote(cargo.get_program())
        );
        for arg in cargo.get_args() {
            line.push(' ');
            line.push_str(&quote(arg));
        }
        if let Some(suffix) = suffix {
            line.push(' ');
            line.push_str(suffix);
        }
        line.push_str("; printf '\\nREADY-STATUS=%s\\n' \"$?\"\n");
        self.send(line.as_bytes());
    }

    fn send(&mut self, bytes: &[u8]) {
        use std::io::Write;
        self.master.write_all(bytes).unwrap();
    }

    fn interrupt(&mut self) {
        self.send(b"\x03");
        // Bash may skip the trailing status printf after an interruption.
        // Keep a status it already printed, or query it at the next prompt.
        let status_cursor = self.cursor;
        self.expect("READY-SHELL> ");
        if !self.output[status_cursor..self.cursor].contains("READY-STATUS=130\r\n") {
            self.send(b"printf '\\nREADY-STATUS=%s\\n' \"$?\"\n");
        }
        self.cursor = status_cursor;
    }

    fn read(&mut self) {
        use std::io::Read;
        use std::os::fd::AsRawFd;
        let mut poll = libc::pollfd {
            fd: self.master.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one live PTY descriptor. Each wait stays short for diagnostics.
        if unsafe { libc::poll(&mut poll, 1, 20) } > 0 {
            let mut bytes = [0; 8192];
            if let Ok(count) = self.master.read(&mut bytes) {
                self.output
                    .push_str(&String::from_utf8_lossy(&bytes[..count]));
            }
        }
    }

    fn expect(&mut self, text: &str) {
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            if let Some(index) = self.output[self.cursor..].find(text) {
                self.cursor += index + text.len();
                return;
            }
            assert!(
                Instant::now() < deadline,
                "missing {text:?}: {}",
                self.output
            );
            self.read();
        }
    }

    fn marker(&mut self, name: &str) {
        let deadline = Instant::now() + Duration::from_secs(15);
        while !self.control.join(name).exists() {
            assert!(Instant::now() < deadline, "missing {name}: {}", self.output);
            self.read();
        }
    }

    fn finish(&mut self, status: i32) {
        use std::os::fd::AsRawFd;
        self.expect(&format!("READY-STATUS={status}\r\n"));
        self.expect("READY-SHELL> ");
        assert_eq!(
            unsafe { libc::tcgetpgrp(self.master.as_raw_fd()) },
            self.shell.id() as i32,
            "terminal not returned to shell: {}",
            self.output
        );
    }
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
impl Drop for TerminalSession {
    fn drop(&mut self) {
        // Also clean up on assertion failure. These groups belong to this PTY's
        // Cargo job/test, never the surrounding test runner or interactive shell.
        for name in ["test-group", "cargo-pid"] {
            if let Ok(pid) = fs::read_to_string(self.control.join(name))
                && let Ok(pid) = pid.trim().parse::<i32>()
                && pid > 1
            {
                unsafe { libc::kill(-pid, libc::SIGKILL) };
            }
        }
        let _ = self.shell.kill();
        let _ = self.shell.wait();
    }
}

#[cargo_test]
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn terminal_input_job_control_and_opt_out() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    for (revision, case) in [
        "input",
        "job-control",
        "job-control-finished-build",
        "job-control-test-stops",
        "job-control-descendant-input",
        "opt-out",
        "tostop",
        "pipeline",
    ]
    .iter()
    .enumerate()
    {
        change(&p, revision);
        let job_control = case.starts_with("job-control");
        let enabled = *case == "input" || job_control;
        let mut cmd = command(
            &p,
            &wrapper,
            if *case == "pipeline" {
                "terminal-pipeline"
            } else if *case == "job-control-descendant-input" {
                "terminal-descendant-input"
            } else if enabled {
                "terminal"
            } else {
                "terminal-fallback"
            },
        );
        if *case == "job-control-descendant-input" {
            cmd.env("READY_TSTP", libc::SIGTSTP.to_string())
                .env("READY_TTIN", libc::SIGTTIN.to_string());
        }
        if *case == "opt-out" {
            cmd.arg("-Zohm-ready-tests=no");
        }
        cmd.arg("--").arg("selected");
        let mut terminal = TerminalSession::new(&p, &mut cmd);
        if *case == "tostop" {
            terminal.send(b"stty tostop\n");
            terminal.expect("READY-SHELL> ");
        }
        let pipeline = (*case == "pipeline").then_some(
            r#"| sh -c 'while [ ! -f "$READY_CONTROL/active" ]; do sleep 0.01; done; IFS= read -r input </dev/tty; printf "%s\n" "$input" > "$READY_CONTROL/input-tmp"; mv "$READY_CONTROL/input-tmp" "$READY_CONTROL/input"; cat'"#,
        );
        terminal.start(&mut cmd, pipeline);
        terminal.marker("active");
        if *case == "job-control-descendant-input" {
            terminal.marker("parent-ready");
            terminal.marker("reader-ready");
        }
        assert_run(&p, if enabled { "during" } else { "after" });
        if matches!(
            *case,
            "job-control-finished-build" | "job-control-test-stops"
        ) {
            fs::write(p.root().join("control/release-build"), "yes").unwrap();
            terminal.expect("Finished");
        }
        if job_control {
            if *case == "job-control-test-stops" {
                let pid = fs::read_to_string(p.root().join("control/active")).unwrap();
                // SAFETY: the fixture published its own PID and is waiting for input.
                assert_eq!(
                    unsafe { libc::kill(pid.trim().parse().unwrap(), libc::SIGSTOP) },
                    0
                );
            } else {
                terminal.send(b"\x1a");
            }
            terminal.expect("Stopped");
            terminal.expect("READY-SHELL> ");
            terminal.send(b"bg\n");
            // Reading stdin in the background must stop the job again.
            terminal.expect("Stopped");
            assert!(!p.root().join("control/input").exists());
            terminal.send(b"fg\n");
        }
        terminal.send(b"hello\n");
        terminal.marker("input");
        fs::write(p.root().join("control/release-build"), "yes").unwrap();
        if job_control {
            // `fg` is a new shell command, so report its status explicitly.
            terminal.expect("READY-SHELL> ");
            terminal.send(b"printf '\\nREADY-STATUS=%s\\n' \"$?\"\n");
        }
        terminal.finish(0);
        assert_run(&p, if enabled { "during" } else { "after" });
        assert!(p.root().join("control/z-ran").exists());
    }
}

#[cargo_test]
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn terminal_cancellation_restores_the_shell_and_stops_descendants() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    for (revision, mode) in [
        "terminal-interrupt",
        "terminal-ignore-int",
        "terminal-finished-build",
        "terminal-build-failure",
    ]
    .iter()
    .enumerate()
    {
        change(&p, revision);
        let mut cmd = command(&p, &wrapper, mode);
        cmd.arg("--").arg("selected");
        let mut terminal = TerminalSession::new(&p, &mut cmd);
        terminal.start(&mut cmd, None);
        terminal.marker("active");
        terminal.marker("slow-active");
        assert_run(&p, "during");
        if matches!(*mode, "terminal-finished-build" | "terminal-build-failure") {
            fs::write(p.root().join("control/release-build"), "yes").unwrap();
        }
        if *mode != "terminal-build-failure" {
            if *mode == "terminal-finished-build" {
                terminal.expect("Finished");
                #[cfg(target_os = "linux")]
                {
                    use std::os::fd::AsRawFd;
                    let relay: i32 = fs::read_to_string(p.root().join("control/test-group"))
                        .unwrap()
                        .parse()
                        .unwrap();
                    // Delay only the relay. Cargo will see the interrupted test
                    // exit before this foreground group leader can forward Ctrl-C.
                    assert!(relay > 1);
                    assert_eq!(
                        unsafe { libc::tcgetpgrp(terminal.master.as_raw_fd()) },
                        relay
                    );
                    assert_eq!(unsafe { libc::kill(relay, libc::SIGSTOP) }, 0);
                    let deadline = Instant::now() + Duration::from_secs(5);
                    while process_state(relay) != Some('T') {
                        assert!(Instant::now() < deadline, "relay {relay} did not stop");
                        std::thread::sleep(Duration::from_millis(5));
                    }
                }
            }
            terminal.interrupt(); // Ctrl-C goes to the test's foreground group.
        }
        terminal.finish(if *mode == "terminal-build-failure" {
            101
        } else {
            130
        });
        #[cfg(target_os = "linux")]
        assert_process_tree_stopped(&p);
    }
}

#[cargo_test]
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn interruption_while_waiting_for_build_lock() {
    let p = project().file("src/lib.rs", "").build();
    fs::create_dir(p.root().join("control")).unwrap();
    fs::create_dir_all(p.target_debug_dir()).unwrap();
    let lock = fs::File::create(p.target_debug_dir().join(".cargo-build-lock")).unwrap();
    lock.lock().unwrap();

    let mut cmd = p.cargo("test --lib -Zohm-defaults=no -Zohm-ready-tests");
    cmd.masquerade_as_nightly_cargo(&["ohm-defaults", "ohm-ready-tests"]);
    let mut terminal = TerminalSession::new(&p, &mut cmd);
    terminal.start(&mut cmd, None);
    terminal.expect("Blocking waiting for file lock on build directory");
    terminal.interrupt();
    terminal.finish(130);
    // Keep the lock held until Cargo exits: acquiring it must not be necessary
    // to process the interrupt.
    drop(lock);
}

#[cargo_test]
#[cfg(any(target_os = "linux", target_os = "macos"))]
fn redirected_stdio_preserves_controlling_terminal_input() {
    let wrapper = wrapper();
    let p = fixture();
    seed(&p, &wrapper);
    change(&p, 1);
    let mut cmd = command(&p, &wrapper, "terminal-redirected");
    cmd.arg("--").arg("selected");
    let mut terminal = TerminalSession::new(&p, &mut cmd);
    terminal.start(
        &mut cmd,
        Some(r#"</dev/null >"$READY_CONTROL/cargo.log" 2>&1"#),
    );
    terminal.marker("active");
    terminal.send(b"hello\n");
    terminal.marker("input");
    terminal.finish(0);
    assert_run(&p, "after");
    assert!(p.root().join("control/z-ran").exists());
}
