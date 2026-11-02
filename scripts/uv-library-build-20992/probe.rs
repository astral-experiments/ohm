use clap::Parser;
use uv_cli::{CacheCommand, Cli, Commands};

fn main() {
    let cases: &[(&str, &[&str])] = &[
        ("default", &[]),
        ("legacy", &["--human"]),
        ("machine", &["--output-format", "machine"]),
        ("human", &["--output-format", "human"]),
        ("auto", &["--output-format", "auto"]),
        ("invalid", &["--output-format", "bogus"]),
        ("conflict", &["--human", "--output-format", "machine"]),
    ];
    for &(name, options) in cases {
        let args = ["uv", "cache", "size"].into_iter().chain(options.iter().copied());
        match Cli::try_parse_from(args) {
            Ok(cli) => {
                assert!(matches!(*cli.command, Commands::Cache(ref ns) if matches!(ns.command, CacheCommand::Size(_))));
                println!("{name} accepted");
            }
            Err(error) => println!("{name} {:?}", error.kind()),
        }
    }
}

