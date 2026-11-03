use ruff_db::vendored::VendoredPath;
fn main() {
    let fs = ty_vendored::file_system();
    print!("{}", ty_vendored::SOURCE_COMMIT);
    for name in ["stdlib/typing.pyi", "stdlib/typing_extensions.pyi"] {
        let data = fs.read_to_string(VendoredPath::new(name)).unwrap();
        print!(" {}", data.matches("Base class for protocol classes.").count());
    }
    println!();
}
