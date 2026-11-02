//@ ignore-cross-compile
//@ needs-target-std

use run_make_support::{run, rust_lib_name, rustc};

fn main() {
    for (cfgs, expected) in [
        (&[][..], "0 0"),
        (&["shared"], "13 0"),
        (&["shared", "unrelated"], "13 0"),
        (&["shared", "mutable"], "13 29"),
        (&["mutable"], "0 29"),
        (&[], "0 0"),
        (&["shared"], "13 0"),
    ] {
        let mut upstream = rustc();
        upstream.input("roster.rs").crate_type("rlib");
        for &cfg in cfgs {
            upstream.cfg(cfg);
        }
        upstream.run();

        rustc()
            .input("reader.rs")
            .extern_("roster", rust_lib_name("roster"))
            .incremental("reader-cache")
            .arg("-Zincremental-verify-ich")
            .run();
        run("reader").assert_stdout_equals(expected);
    }
}
