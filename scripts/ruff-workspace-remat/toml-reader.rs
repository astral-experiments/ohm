use ruff_workspace::options::Options;

fn main() {
    let input = std::env::args().nth(1).expect("one document");
    let table = match input.parse::<toml::Table>() {
        Ok(table) => table,
        Err(_) => {
            println!("invalid TOML syntax");
            std::process::exit(2);
        }
    };
    match Options::from_toml_table(table) {
        Ok(options) => println!("line-length={}", options.line_length.expect("provided")),
        Err(error) => {
            println!("{}", error.message());
            std::process::exit(3);
        }
    }
}
