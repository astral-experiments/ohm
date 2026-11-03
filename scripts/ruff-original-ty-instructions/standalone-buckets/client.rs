use ruff_db::files::system_path_to_file;
use ruff_db::system::{InMemorySystem, SystemPath};
use ty_project::{Db, ProjectDatabase, ProjectMetadata, UseUv};

fn main() {
    let root = std::env::args().nth(1).unwrap();
    let root = SystemPath::new(&root);
    for (name, expected) in [
        ("stdlib/os.pyi", Some("stdlib/os.pyi")),
        ("../other.pyi", None),
        ("../fixture-sibling/os.pyi", None),
    ] {
        let absolute = if name.starts_with("../") {
            root.parent()
                .unwrap()
                .join(name.strip_prefix("../").unwrap())
        } else {
            root.join(name)
        };
        let result = ty_ide::map_system_to_vendored(root, &absolute);
        assert_eq!(result.map(|p| p.as_str()), expected);
    }
    for mode in [UseUv::Off, UseUv::Scripts] {
        let metadata = ProjectMetadata::new("owner-oracle", root.to_path_buf()).with_use_uv(mode);
        let system = InMemorySystem::default();
        let path = root.join("script.py");
        system.fs().write_file_all(&path, std::fs::read(path.as_str()).unwrap()).unwrap();
        let db = ProjectDatabase::use_defaults(metadata, system);
        let project = db.project();
        let file = system_path_to_file(&db, &root.join("script.py")).unwrap();
        #[cfg(old_build)]
        let selected: Vec<_> = project.script_files(&db).iter().collect();
        #[cfg(not(old_build))]
        let selected = project.scripts_to_synchronize(&db);
        if !selected.is_empty() {
            assert_eq!(selected, [file]);
        }
        println!("scripts={}", selected.len());
    }
    println!("vendored-paths=3");
}
