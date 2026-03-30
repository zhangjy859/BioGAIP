import yaml
import subprocess
import re
import requests
import sys
from typing import Dict, List, Tuple

def parse_package_spec(spec: str) -> Tuple[str, str]:
    """
    Parse package spec like 'package=1.0=build' or 'package==1.0' or 'package'.
    Returns (name, version) where version is '' if not specified, ignoring build.
    """
    # Handle '==' first for pip-style
    if '==' in spec:
        parts = spec.split('==')
        name = parts[0].strip()
        version = '=='.join(parts[1:]).strip()  # In case multiple, but rare
    else:
        parts = spec.split('=')
        name = parts[0].strip()
        version = parts[1].strip() if len(parts) > 1 else ''
        # If build present (len > 2), ignore it, keep only version
    return name, version

def get_conda_package_size(name: str, version: str) -> str:
    """
    Use conda search --info to get package size.
    Returns size as string (e.g., '5.2 MB') or 'Unknown' if not found.
    """
    #sys.stderr.write(f"{name}: \n")
    if name.startswith('_'):
        return 'Unknown'
    try:
        cmd = ['conda', 'search', '--info']
        if version:
            cmd.append(f'{name}={version}')
        else:
            cmd.append(name)
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        
        # Parse size from output
        size_match = re.search(r'size\s+:\s+([\d.]+\s+[KMG]?B)', output, re.IGNORECASE)
        sys.stderr.write(f"{name}:{size_match}\n")
        if size_match:
            return size_match.group(1)
        else:
            return 'Unknown'
    except subprocess.CalledProcessError:
        sys.stderr.write(f"{name} check no return \n")
        return 'Error querying conda'

def get_pip_package_size(name: str, version: str) -> str:
    """
    Query PyPI JSON API to get package size (largest upload size).
    Returns size as string (e.g., '5.2 MB') or 'Unknown'.
    """
    try:
        url = f'https://pypi.org/pypi/{name}'
        if version:
            url += f'/{version}'
        url += '/json'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        max_size = 0
        for upload in data.get('urls', []):
            size = upload.get('size', 0)
            if size > max_size:
                max_size = size
        
        if max_size > 0:
            if max_size < 1024:
                return f'{max_size} B'
            elif max_size < 1024 * 1024:
                return f'{max_size / 1024:.1f} KB'
            elif max_size < 1024 * 1024 * 1024:
                return f'{max_size / (1024 * 1024):.1f} MB'
            else:
                return f'{max_size / (1024 * 1024 * 1024):.1f} GB'
        else:
            return 'Unknown'
    except requests.RequestException:
        return 'Error querying PyPI'

def main(yaml_file: str):
    with open(yaml_file, 'r') as f:
        data = yaml.safe_load(f)
    
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
        size = get_conda_package_size(name, version)
        print(f"{name}=={version or 'latest'}: {size}")
    
    print("\nPip Packages:")
    for name, version in pip_packages:
        size = get_pip_package_size(name, version)
        print(f"{name}=={version or 'latest'}: {size}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py env.yaml")
        sys.exit(1)
    main(sys.argv[1])
