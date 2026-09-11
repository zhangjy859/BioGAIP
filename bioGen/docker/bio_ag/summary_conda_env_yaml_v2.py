import yaml
import subprocess
import re
import requests
import sys
import json
import bz2
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

def parse_package_spec(spec: str) -> Tuple[str, str]:
    """
    Parse package spec like 'package=1.0=build' or 'package==1.0' or 'package'.
    Returns (name, version) where version is '' if not specified, ignoring build.
    """
    if '==' in spec:
        parts = spec.split('==')
        name = parts[0].strip()
        version = '=='.join(parts[1:]).strip()
    else:
        parts = spec.split('=')
        name = parts[0].strip()
        version = parts[1].strip() if len(parts) > 1 else ''
    return name, version

def version_key(v: str) -> tuple:
    """
    Simple version key for comparison, e.g., '1.10' > '1.9'.
    """
    parts = re.split(r'(\d+)', v)
    return tuple(int(p) if p.isdigit() else p for p in parts if p)

def format_size(size: int) -> str:
    """
    Format bytes to human-readable string.
    """
    if size < 1024:
        return f'{size} B'
    elif size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    elif size < 1024 * 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    else:
        return f'{size / (1024 * 1024 * 1024):.1f} GB'

def get_base_url(channel: str) -> str:
    """
    Get base URL for short channel name.
    """
    if channel == 'defaults':
        return 'https://repo.anaconda.com/pkgs/main'
    elif channel == 'r':
        return 'https://repo.anaconda.com/pkgs/r'
    elif channel == 'msys2':
        return 'https://repo.anaconda.com/pkgs/msys2'
    else:
        return f'https://conda.anaconda.org/{channel}'

def fetch_repodatas(channels: List[str], subdir: str) -> List[Dict]:
    repodatas = []
    seen = set()  # Avoid duplicate fetches
    for channel in channels:
        if channel in seen:
            continue
        seen.add(channel)
        if channel.startswith(('http://', 'https://')):
            # Full channel URL (includes subdir or noarch)
            url_bz2 = f"{channel.rstrip('/')}/repodata.json.bz2"
            url_json = f"{channel.rstrip('/')}/repodata.json"
            data = fetch_single_repodata(url_bz2, url_json)
            if data:
                repodatas.append(data)
        else:
            # Short channel name, fetch for subdir and noarch
            base = get_base_url(channel)
            for sd in [subdir, 'noarch']:
                url_bz2 = f"{base}/{sd}/repodata.json.bz2"
                url_json = f"{base}/{sd}/repodata.json"
                data = fetch_single_repodata(url_bz2, url_json)
                if data:
                    repodatas.append(data)
    return repodatas

def fetch_single_repodata(url_bz2: str, url_json: str) -> Dict | None:
    data = None
    try:
        r = requests.get(url_bz2, timeout=10)
        r.raise_for_status()
        data = json.loads(bz2.decompress(r.content))
    except Exception as e:
        sys.stderr.write(f"Failed to fetch {url_bz2}: {e}. Trying JSON...\n")
        try:
            r = requests.get(url_json, timeout=10)
            r.raise_for_status()
            data = json.loads(r.text)
        except Exception as e:
            sys.stderr.write(f"Failed to fetch {url_json}: {e}\n")
    return data

def get_conda_package_size(name: str, version: str, repodatas: List[Dict]) -> str:
    """
    Get package size from repodatas.
    """
    sys.stderr.write(f"Querying {name}...\n")
    if name.startswith('_'):
        return 'Unknown'
    
    latest_v = None
    latest_size = None
    
    for repodata in repodatas:
        all_packages = {**repodata.get('packages', {}), **repodata.get('packages.conda', {})}
        for info in all_packages.values():
            if info['name'] == name:
                this_v = info['version']
                this_size = info.get('size', 0)
                if version and this_v == version:
                    formatted_size = format_size(this_size)
                    sys.stderr.write(f"Found exact: {name}=={version}, size {formatted_size}\n")
                    return formatted_size
                elif not version:
                    if latest_v is None or version_key(this_v) > version_key(latest_v):
                        latest_v = this_v
                        latest_size = this_size
    
    if version:
        return 'Unknown'  # Exact version not found
    elif latest_size:
        formatted_size = format_size(latest_size)
        sys.stderr.write(f"Found latest: {name}=={latest_v}, size {formatted_size}\n")
        return formatted_size
    else:
        return 'Unknown'

def get_pip_package_size(name: str, version: str) -> str:
    """
    Query PyPI JSON API (trying Tsinghua mirror first, then official) to get package size (largest upload size).
    Returns size as string (e.g., '5.2 MB') or 'Unknown'.
    """
    mirrors = [
        #'https://pypi.tuna.tsinghua.edu.cn',
        'https://pypi.org'
    ]
    for base in mirrors:
        try:
            url = f'{base}/pypi/{name}'
            if version:
                url += f'/{version}'
            url += '/json'
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            max_size = 0
            for upload in data.get('urls', []):
                size = upload.get('size', 0)
                if size > max_size:
                    max_size = size

            if max_size > 0:
                return format_size(max_size)
            else:
                return 'Unknown'
        except requests.RequestException as e:
            sys.stderr.write(f"Error querying {base} for {name}=={version or 'latest'}: {e}\n")
    return 'Unknown'

def get_conda_info() -> Dict:
    output = subprocess.check_output(['conda', 'info', '--json'], text=True)
    return json.loads(output)

def main(yaml_file: str):
    with open(yaml_file, 'r') as f:
        data = yaml.safe_load(f)

    conda_info = get_conda_info()
    subdir = conda_info.get('platform', 'linux-64')  # Fallback to common default if missing
    
    default_channels = conda_info.get('channels', [])
    channels = data.get('channels', default_channels)
    
    repodatas = fetch_repodatas(channels, subdir)

    dependencies = data.get('dependencies', [])

    conda_packages: List[Tuple[str, str]] = []
    pip_packages: List[Tuple[str, str]] = []

    for dep in dependencies:
        if isinstance(dep, str):
            conda_packages.append(parse_package_spec(dep))
        elif isinstance(dep, dict) and 'pip' in dep:
            for pip_dep in dep['pip']:
                pip_packages.append(parse_package_spec(pip_dep))

    print("Conda Packages:")
    for name, version in conda_packages:
        size = get_conda_package_size(name, version, repodatas)
        print(f"{name}=={version or 'latest'}: {size}")

    print("\nPip Packages:")
    if pip_packages:
        def fetch_pip_size(pkg):
            name, version = pkg
            size = get_pip_package_size(name, version)
            return name, version, size

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pkg = {executor.submit(fetch_pip_size, pkg): pkg for pkg in pip_packages}
            for future in as_completed(future_to_pkg):
                name, version, size = future.result()
                print(f"{name}=={version or 'latest'}: {size}")
    else:
        print("No PIP packages.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py env.yaml")
        sys.exit(1)
    main(sys.argv[1])
