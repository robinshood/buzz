//! Parses every workflow YAML under `life-ops/workflows/` with the real
//! `buzz-workflow` schema code (the same validation the relay applies on
//! `workflows create`), including cron expressions. Exits non-zero on any failure.

use std::path::{Path, PathBuf};

fn collect_yaml(dir: &Path, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect_yaml(&path, out)?;
        } else if path.extension().is_some_and(|e| e == "yaml" || e == "yml") {
            out.push(path);
        }
    }
    Ok(())
}

fn main() {
    let workflows_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../workflows");
    let mut files = Vec::new();
    if let Err(e) = collect_yaml(&workflows_dir, &mut files) {
        eprintln!("FAIL reading {}: {e}", workflows_dir.display());
        std::process::exit(1);
    }
    files.sort();

    if files.is_empty() {
        eprintln!("FAIL: no YAML files found under {}", workflows_dir.display());
        std::process::exit(1);
    }

    let mut failed = 0usize;
    for file in &files {
        let rel = file
            .strip_prefix(workflows_dir.parent().unwrap_or(&workflows_dir))
            .unwrap_or(file);
        match std::fs::read_to_string(file) {
            Ok(yaml) => match buzz_workflow::schema::parse_yaml(&yaml) {
                Ok((def, _json)) => {
                    println!("PASS  {}  ({})", rel.display(), def.name);
                }
                Err(e) => {
                    failed += 1;
                    println!("FAIL  {}  {e}", rel.display());
                }
            },
            Err(e) => {
                failed += 1;
                println!("FAIL  {}  read error: {e}", rel.display());
            }
        }
    }

    println!("\n{} file(s), {} failure(s)", files.len(), failed);
    if failed > 0 {
        std::process::exit(1);
    }
}
