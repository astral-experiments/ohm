use ruff_db::system::{InMemorySystem, SystemPath, SystemPathBuf};
use salsa::plumbing::current_revision;
use ty_project::watch::ChangeEvent;
use ty_project::{Db, ProjectDatabase, ProjectMetadata};

fn main() {
    let root = SystemPath::new("/project");
    let stub = root.join("stdlib/os.pyi");
    assert_eq!(
        ty_ide::map_system_to_vendored(root, &stub)
            .unwrap()
            .as_str(),
        "stdlib/os.pyi"
    );
    let system = InMemorySystem::default();
    let files = system.fs().clone();
    files.write_file_all(root.join("main.py"), "").unwrap();
    let unrelated = SystemPathBuf::from("/project/unrelated.log");
    files.write_file_all(&unrelated, "before").unwrap();
    let metadata = ProjectMetadata::new("owner-lanes", root.to_path_buf());
    let mut db = ProjectDatabase::fallible(metadata, system).unwrap();
    db.project().files(&db);
    let prior = current_revision(&db);
    files.write_file_all(&unrelated, "after").unwrap();
    db.apply_changes(&[ChangeEvent::file_content_changed(unrelated)]);
    println!("unrelated-preserved={}", current_revision(&db) == prior);
    println!("vendored-path=stdlib/os.pyi");
}
