import argparse
import shlex
import sys
from pathlib import Path
import shutil
import os
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
        sys.exit(f"Source directory does not exist: {source_dir}")
    if not file_list_path.is_file():
        sys.exit(f"file_list.txt does not exist: {file_list_path}")

    # Read and parse all lines
    tasks = []
    with open(file_list_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue  # Ignore empty lines and comments

            try:
                tokens = shlex.split(line)
            except ValueError as e:
                sys.exit(f"Error parsing line {line_num}: {e}")

            if len(tokens) not in (1, 2):
                sys.exit(f"Invalid number of values on line {line_num}: {line}")

            # Check if any token is absolute path
            for token in tokens:
                if Path(token).is_absolute():
                    sys.exit(f"Absolute path detected on line {line_num}: {token}")

            src_rel = tokens[0]
            if len(tokens) == 1:
                dest_rel = tokens[0]
            else:
                dest_rel = tokens[1]

            src_path = source_dir / src_rel
            dest_path = output_dir / dest_rel

            if not src_path.exists():
                sys.exit(f"Source path does not exist on line {line_num}: {src_path}")

            tasks.append((src_path, dest_path))

    if args.dry_run:
        for src, dest in tasks:
            print(f"Would copy {src} to {dest}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

        all_dirs = set()
        all_files = []

        for src, dest in tasks:
            if src.is_file():
                if dest.parent != output_dir:
                    all_dirs.add(dest.parent)
                all_files.append((src, dest))
            elif src.is_dir():
                for root, dirnames, filenames in os.walk(src):
                    dest_root = dest / Path(root).relative_to(src)
                    all_dirs.add(dest_root)
                    for filename in filenames:
                        src_file = Path(root) / filename
                        dest_file = dest_root / filename
                        all_files.append((src_file, dest_file))
            else:
                continue  # Should not reach here due to earlier check

        # Create all directories
        for d in all_dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Parallel copy files with progress
        if all_files:
            max_workers = os.cpu_count() or 4
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                def copy_func(s, d):
                    shutil.copy2(s, d)

                futures = [executor.submit(copy_func, s, d) for s, d in all_files]
                pbar = tqdm(total=len(all_files), desc="Copying files")
                for future in as_completed(futures):
                    future.result()  # Raise any exceptions
                    pbar.update(1)
                pbar.close()

if __name__ == "__main__":
    main()