import requests
import json
import time
from tqdm import tqdm
from bs4 import BeautifulSoup


def get_channel_repodata(channel_url, platform="linux-64"):
    """Fetch repodata.json data for a specific channel and platform"""
    repodata_url = f"{channel_url}/{platform}/repodata.json"
    try:
        response = requests.get(repodata_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching {repodata_url}: {e}")
        return None


def get_org_from_channel(channel_name):
    """Map channel name to Anaconda.org org"""
    if channel_name == 'main':
        return 'anaconda'
    elif channel_name == 'r':
        return 'r'
    else:
        return channel_name


def get_description(org, package_name):
    """Fetch package description from Anaconda.org page"""
    url = f"https://anaconda.org/{org}/{package_name}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        desc_h3 = soup.find('h3', string='Description')
        if desc_h3:
            desc_p = desc_h3.find_next('p')
            if desc_p:
                return desc_p.text.strip()
        return "Description not found"
    except Exception as e:
        print(f"Error fetching description for {package_name} in {org}: {e}")
        return "Error"


def crawl_conda_packages(channels, platforms):
    """Crawl conda package info from multiple channels and platforms"""
    all_packages = {}

    for channel in channels:
        channel_name = channel.split('/')[-1]
        print(f"Crawling channel: {channel} (name: {channel_name})")
        # Use tqdm for progress bar over platforms
        for platform in tqdm(platforms, desc=f"Progress for {channel_name}"):
            repodata = get_channel_repodata(channel, platform)
            if repodata and "packages" in repodata:
                for filename, pkg_info in repodata["packages"].items():
                    package_name = pkg_info.get("name", "")
                    if not package_name:
                        continue
                    # Extract key information
                    package_data = {
                        "package_name": package_name,
                        "filename": filename,
                        "full_name": f"{channel_name}::{package_name}",
                        "version": pkg_info.get("version", ""),
                        "build": pkg_info.get("build", ""),
                        "channel": channel,
                        "channel_name": channel_name,
                        "platform": platform,
                        "depends": pkg_info.get("depends", []),
                        "md5": pkg_info.get("md5", ""),
                        "size": pkg_info.get("size", 0)
                    }
                    # Unique key
                    unique_key = f"{package_name}_{pkg_info.get('version')}_{pkg_info.get('build')}_{platform}_{channel_name}"
                    all_packages[unique_key] = package_data
            time.sleep(2)  # Increased sleep to prevent rate limiting

    return all_packages


def add_descriptions(all_packages):
    """Add descriptions to packages by crawling unique (channel, package) pairs"""
    # Collect unique (channel_name, package_name) pairs
    unique_pairs = set()
    for data in all_packages.values():
        unique_pairs.add((data["channel_name"], data["package_name"]))

    # Dictionary to store descriptions
    descriptions = {}

    # Crawl descriptions with progress bar
    for channel_name, package_name in tqdm(unique_pairs, desc="Fetching descriptions"):
        org = get_org_from_channel(channel_name)
        desc = get_description(org, package_name)
        descriptions[(channel_name, package_name)] = desc
        time.sleep(2)  # Prevent rate limiting

    # Assign descriptions to all packages
    for data in all_packages.values():
        key = (data["channel_name"], data["package_name"])
        data["description"] = descriptions.get(key, "Description not available")

    return all_packages


def save_to_json(data, output_file):
    """Save data to a JSON file"""
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Data saved to {output_file}")


def main():
    # Define channels to crawl (using Tsinghua mirrors for speed)
    channels = [
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/bioconda",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/msys2",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/fastai",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/peterjc123",
        #"https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/menpo"
        # Add more channels if needed
    ]

    # Define platforms
    platforms = ["linux-64", "win-64", "osx-64", "osx-arm64", "win-32", "linux-aarch64", "noarch"]

    # Crawl basic package info
    packages = crawl_conda_packages(channels, platforms)

    # Add descriptions
    packages = add_descriptions(packages)

    # Save to JSON file
    save_to_json(packages, "conda_packages.json")


if __name__ == "__main__":
    main()