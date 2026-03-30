import argparse
import shlex
import sys
import shutil
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def main():
    parser = argparse.ArgumentParser(description="Copy files/directories based on file_list.txt")
    parser.add_argument("source", type=str, help="Source directory")
    parser.add_argument("output", type=str, help="Output directory")
    parser.add_argument("file_list", type=str, help="Path to file_list.txt")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without copying")
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    output_dir = Path(args.output).resolve()
    file_list_path = Path(args.file_list).resolve()

    if not source_dir.is_dir():
        sys.exit(f"Error: Source directory does not exist: {source_dir}")
    if not file_list_path.is_file():
        sys.exit(f"Error: file_list.txt does not exist: {file_list_path}")

    tasks = []
    failures = []

    with open(file_list_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue  # Skip empty lines and comments

            try:
                tokens = shlex.split(line)
            except ValueError as e:
                failures.append((f"Line {line_num}", f"Parse error: {e}"))
                continue

            if len(tokens) not in (1, 2):
                failures.append((f"Line {line_num} '{line}'", "Invalid token count"))
                continue

            if any(Path(t).is_absolute() for t in tokens):
                failures.append((f"Line {line_num} '{line}'", "Absolute path not allowed"))
                continue

            src_rel = tokens[0]
            dest_rel = tokens[0] if len(tokens) == 1 else tokens[1]

            src_path = source_dir / src_rel
            dest_path = output_dir / dest_rel

            if not src_path.exists():
                failures.append((str(src_path), "Source path does not exist"))
                continue

            tasks.append((src_path, dest_path))

    if args.dry_run:
        for src, dest in tasks:
            print(f"Would copy {src} to {dest}")
        if failures:
            print("\n--- Failures (Dry Run) ---")
            for item, err in failures:
                print(f"[SKIP] {item} | Reason: {err}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    all_dirs = set()
    all_files = []

    for src, dest in tasks:
        try:
            if src.is_file():
                all_dirs.add(dest.parent)
                all_files.append((src, dest))
            elif src.is_dir():
                for root, _, filenames in os.walk(src):
                    dest_root = dest / Path(root).relative_to(src)
                    all_dirs.add(dest_root)
                    for filename in filenames:
                        all_files.append((Path(root) / filename, dest_root / filename))
        except Exception as e:
            failures.append((str(src), f"Task resolution error: {e}"))

    for d in all_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            failures.append((str(d), f"Mkdir error: {e}"))

    if all_files:
        max_workers = os.cpu_count() or 4
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            def copy_func(s, d):
                try:
                    shutil.copy2(s, d)
                    return True, s, None
                except Exception as e:
                    return False, s, str(e)

            futures = [executor.submit(copy_func, s, d) for s, d in all_files]
            
            with tqdm(total=len(all_files), desc="Copying files") as pbar:
                for future in as_completed(futures):
                    success, s, err = future.result()
                    if not success:
                        failures.append((str(s), f"Copy failed: {err}"))
                    pbar.update(1)

    if failures:
        print("\n--- Failed Items Summary ---")
        for item, err in failures:
            print(f"[FAILED] {item} | Reason: {err}")
        print(f"\nTotal failures: {len(failures)}")
    else:
        print("\nAll tasks completed successfully!")

if __name__ == "__main__":
    main()