use ruff_db::system::{InMemorySystem, SystemPath, SystemPathBuf};
use salsa::{Cancelled, Database};
use std::panic::AssertUnwindSafe;
use std::sync::mpsc;
use std::thread;
use ty_project::watch::ChangeEvent;
use ty_project::{Db, ProjectDatabase, ProjectMetadata};

// An old writer waits for all snapshots to drop. The snapshot must catch PendingWrite
// before such a writer can return. A non-writing action signals the snapshot to finish.
fn cancels_snapshot(db: &mut ProjectDatabase, action: impl FnOnce(&mut ProjectDatabase)) -> bool {
    thread::scope(|scope| {
        let snapshot = db.clone();
        let (completed, receiver) = mpsc::channel::<()>();
        let reader = scope.spawn(move || {
            loop {
                match Cancelled::catch(AssertUnwindSafe(|| snapshot.unwind_if_revision_cancelled()))
                {
                    Err(Cancelled::PendingWrite) => return true,
                    Err(other) => panic!("unexpected Salsa cancellation: {other}"),
                    Ok(()) => {}
                }
                match receiver.try_recv() {
                    Ok(()) => return false,
                    Err(mpsc::TryRecvError::Empty) => thread::yield_now(),
                    Err(mpsc::TryRecvError::Disconnected) => panic!("writer exited"),
                }
            }
        });
        action(db);
        let _ = completed.send(());
        reader.join().unwrap()
    })
}

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
    assert!(!cancels_snapshot(&mut db, |_| {}));
    assert!(cancels_snapshot(&mut db, |db| db.trigger_cancellation()));
    files.write_file_all(&unrelated, "after").unwrap();
    let cancelled = cancels_snapshot(&mut db, |db| {
        db.apply_changes(&[ChangeEvent::file_content_changed(unrelated)]);
    });
    println!("unrelated-preserved={}", !cancelled);
    println!("vendored-path=stdlib/os.pyi");
}
