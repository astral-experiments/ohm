use ruff_db::files::{system_path_to_file, Files};
use ruff_db::system::{System, SystemPath, TestSystem};
use ruff_db::vendored::VendoredFileSystem;
use ruff_db::{Db, PythonFile};
use ruff_python_ast::{AnyRootNodeRef, NodeIndex, PythonVersion};

#[salsa::db]
#[derive(Default, Clone)]
struct Database {
    storage: salsa::Storage<Self>,
    files: Files,
    fs: TestSystem,
    vendored: VendoredFileSystem,
}

#[salsa::db]
impl salsa::Database for Database {}

#[salsa::db]
impl Db for Database {
    fn files(&self) -> &Files { &self.files }
    fn system(&self) -> &dyn System { &self.fs }
    fn vendored(&self) -> &VendoredFileSystem { &self.vendored }
}

fn main() {
    let db = Database::default();
    let cli: Vec<_> = std::env::args().collect();
    let count: u32 = cli[1].parse().unwrap();
    assert!(count == 1 || count == 65);
    let path = SystemPath::new("/packed.py");
    db.fs.as_writable().unwrap().write_file(path, &"pass\n".repeat(count as usize)).unwrap();
    let file = system_path_to_file(&db, path).unwrap();
    let parsed = ruff_db::parsed::parsed_module(&db, PythonFile::new(&db, file, PythonVersion::PY313));
    let reference = parsed.load(&db);
    for i in 0..count {
        assert!(matches!(reference.get_by_index(NodeIndex::from(i)), AnyRootNodeRef::Stmt(_)));
    }
    println!("read {count} distinct packed statements");
    if cli.get(2).map(String::as_str) == Some("past-end") {
        std::panic::set_hook(Box::new(|_| {}));
        let result=std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            reference.get_by_index(NodeIndex::from(count));
        }));
        let payload = result.expect_err("past-end index was accepted");
        let why = payload.downcast_ref::<String>().map(String::as_str)
            .or_else(|| payload.downcast_ref::<&str>().copied()).unwrap();
        assert_eq!(why, format!("index out of bounds: the len is {count} but the index is {count}"));
        println!("{why}");
    }
}
