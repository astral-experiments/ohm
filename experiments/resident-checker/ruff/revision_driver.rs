#![feature(rustc_private)]

//! A coordinator for arbitrary on-disk revisions of one captured rustc invocation.
//!
//! Requests are `compile\t<version>` and `quit`. Stdout reports readiness, the
//! coordinator PID and exit status for each result, and shutdown; stderr surrounds
//! compiler diagnostics with markers and reports the actual compiler PID and route.
//! The default route starts a new child for every request. Setting
//! `OHM_ARBITRARY_REUSE_PROCESS=1` opts into using the coordinator as the compiler,
//! which is only safe for inputs known to be free of procedural macros.

extern crate rustc_driver;

use std::io::{self, BufRead, Write};
use std::process::{Command, ExitCode, Stdio};
use std::time::Instant;

struct FreshCallbacks;

impl rustc_driver::Callbacks for FreshCallbacks {}

fn response(message: std::fmt::Arguments<'_>) -> io::Result<()> {
    let mut stream = io::stdout().lock();
    writeln!(stream, "{message}")?;
    stream.flush()
}

fn marker(phase: &str, version: &str) -> io::Result<()> {
    let mut stream = io::stderr().lock();
    writeln!(stream, "resident-{phase}\t{version}")?;
    stream.flush()
}

fn route(version: &str, method: &str, pid: u32) -> io::Result<()> {
    let mut stream = io::stderr().lock();
    writeln!(stream, "resident-route\t{version}\t{method}\t{pid}")?;
    stream.flush()
}

fn compile(args: &[String]) -> ExitCode {
    // A new invocation reparses current files and owns a new compiler session, query
    // context, source map, and diagnostics. Stock disk incremental state is reused
    // only when the caller supplied its ordinary compiler argument.
    rustc_driver::catch_with_exit_code(|| rustc_driver::run_compiler(args, &mut FreshCallbacks))
}

fn main() -> io::Result<ExitCode> {
    // rustc takes argv[0] too. Source inputs must be files: stdin and stdout belong to
    // the protocol. Normal compilation diagnostics use stderr, between our markers.
    let args = std::env::args().collect::<Vec<_>>();
    if args.len() == 1 {
        return Err(io::Error::other("expected rustc compilation arguments"));
    }
    if std::env::var("OHM_ARBITRARY_COMPILER_CHILD").as_deref() == Ok("1") {
        return Ok(compile(&args));
    }

    let pid = std::process::id();
    // A fresh child is required by default: procedural macros can keep global state
    // and loaded dynamic libraries alive beyond one compiler invocation. Reusing this
    // process is an experimental opt-in for inputs known to be free of those macros.
    let reuse = std::env::var("OHM_ARBITRARY_REUSE_PROCESS").as_deref() == Ok("1");
    response(format_args!("ready\t{pid}"))?;

    for line in io::stdin().lock().lines() {
        let line = line?;
        if line == "quit" {
            break;
        }
        let Some(("compile", version)) = line.split_once('\t') else {
            response(format_args!("protocol-error\t{pid}\tinvalid-request"))?;
            continue;
        };
        if version.is_empty() || version.chars().any(char::is_control) {
            response(format_args!("protocol-error\t{pid}\tinvalid-version"))?;
            continue;
        }

        marker("started", version)?;
        let started = Instant::now();
        let (method, compiler_pid, status) = if reuse {
            let status = if compile(&args) == ExitCode::SUCCESS {
                rustc_driver::EXIT_SUCCESS
            } else {
                rustc_driver::EXIT_FAILURE
            };
            ("same-process", pid, status)
        } else {
            let mut child = Command::new(std::env::current_exe()?)
                .args(&args[1..])
                .env("OHM_ARBITRARY_COMPILER_CHILD", "1")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::inherit())
                .spawn()?;
            let compiler_pid = child.id();
            let status = child.wait()?.code().unwrap_or(-1);
            ("fresh-process", compiler_pid, status)
        };
        let elapsed = started.elapsed().as_nanos();
        route(version, method, compiler_pid)?;
        marker("finished", version)?;
        response(format_args!(
            "result\t{version}\t{pid}\t{status}\t{elapsed}"
        ))?;
    }

    response(format_args!("bye\t{pid}"))?;
    Ok(ExitCode::SUCCESS)
}
