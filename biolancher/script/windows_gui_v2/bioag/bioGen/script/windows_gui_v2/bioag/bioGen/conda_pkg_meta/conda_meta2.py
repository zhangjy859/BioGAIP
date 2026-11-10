from pathlib import Path

import requests
import json
import time
import asyncio
import aiohttp
from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from tqdm import tqdm
from bs4 import BeautifulSoup
import pickle
from concurrent.futures import ThreadPoolExecutor
import os
from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientResponseError


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


async def fetch_description(session, org, package_name, semaphore, retries=3):
    """Asynchronously fetch package description from Anaconda.org page with retries"""
    url = f"https://anaconda.org/{org}/{package_name}"
    for attempt in range(retries):
        async with semaphore:  # Limit concurrent requests
            try:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    html = await response.text()
                    return org, package_name, html
            except ClientResponseError as e:
                print(f"Attempt {attempt + 1}/{retries} failed for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except Exception as e:
                print(f"Error fetching description for {package_name} in {org}: {e}")
                break
    # Save failed URL for debugging
    with open("failed_pages.log", "a", encoding="utf-8") as f:
        f.write(f"Failed to fetch: {url}\n")
    return org, package_name, None


def parse_description(html, org, package_name):
    """Parse description from HTML content with flexible matching"""
    if not html:
        return "Error"
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Try finding <h3> with "Description" (case-insensitive, partial match)
        desc_h3 = soup.find('h3', string=lambda text: text and 'description' in text.lower())
        if desc_h3:
            desc_p = desc_h3.find_next('p')
            if desc_p:
                return desc_p.text.strip()
        # Fallback: Look for <p> with class containing 'description'
        desc_p = soup.find('p', class_=lambda x: x and 'description' in x.lower())
        if desc_p:
            return desc_p.text.strip()
        # Fallback: Look for any <p> under a div with class containing 'description'
        desc_div = soup.find('div', class_=lambda x: x and 'description' in x.lower())
        if desc_div:
            desc_p = desc_div.find('p')
            if desc_p:
                return desc_p.text.strip()
        # Save HTML for debugging
        os.makedirs("failed_pages", exist_ok=True)
        with open(f"failed_pages/{org}_{package_name}.html", "w", encoding="utf-8") as f:
            f.write(str(soup.prettify()))
        return "Description not found"
    except Exception as e:
        print(f"Error parsing HTML for {package_name} in {org}: {e}")
        return "Error"


async def get_descriptions(unique_pairs, max_concurrent=5, reset_cache=False):
    """Fetch descriptions for unique (channel_name, package_name) pairs asynchronously"""
    # Create directory for failed HTML pages
    os.makedirs("failed_pages", exist_ok=True)

    # Load cached descriptions if available and not resetting
    cache_file = "descriptions_cache.pkl"
    if not reset_cache and os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            descriptions = pickle.load(f)
    else:
        descriptions = {}

    # Identify pairs that need fetching
    to_fetch = [(channel_name, pkg_name) for channel_name, pkg_name in unique_pairs
                if (channel_name, pkg_name) not in descriptions or descriptions[(channel_name, pkg_name)] in ["Description not found", "Error"]]

    if not to_fetch:
        return descriptions

    # Semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(max_concurrent)

    async with ClientSession() as session:
        tasks = [
            fetch_description(session, get_org_from_channel(channel_name), package_name, semaphore)
            for channel_name, package_name in to_fetch
        ]
        # Fetch all descriptions with progress bar
        results = []
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Fetching descriptions"):
            results.append(await f)

    # Parse HTML in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor() as executor:
        parsed_results = list(tqdm(
            executor.map(lambda x: (x[0], x[1], parse_description(x[2], x[0], x[1])), results),
            total=len(results),
            desc="Parsing descriptions"
        ))

    # Update descriptions dictionary
    for org, package_name, desc in parsed_results:
        channel_name = next(cn for cn in unique_pairs if get_org_from_channel(cn[0]) == org and cn[1] == package_name)
        descriptions[(channel_name, package_name)] = desc

    # Save updated cache
    with open(cache_file, "wb") as f:
        pickle.dump(descriptions, f)

    return descriptions


def crawl_conda_packages(channels, platforms):
    """Crawl conda package info from multiple channels and platforms"""
    all_packages = {}

    for channel in channels:
        channel_name = channel.split('/')[-1]
        print(f"Crawling channel: {channel} (name: {channel_name})")
        for platform in tqdm(platforms, desc=f"Progress for {channel_name}"):
            repodata = get_channel_repodata(channel, platform)
            if repodata and "packages" in repodata:
                for filename, pkg_info in repodata["packages"].items():
                    package_name = pkg_info.get("name", "")
                    if not package_name:
                        continue
                    # Check repodata for description (fallback if web scraping fails)
                    description = pkg_info.get("description", "Description not available")
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
                        "size": pkg_info.get("size", 0),
                        "description": description  # Initialize with repodata description if available
                    }
                    # Unique key
                    unique_key = f"{package_name}_{pkg_info.get('version')}_{pkg_info.get('build')}_{platform}_{channel_name}"
                    all_packages[unique_key] = package_data
            time.sleep(2)  # Prevent rate limiting

    return all_packages


def add_descriptions(all_packages, reset_cache=False):
    """Add descriptions to packages by crawling unique (channel, package) pairs"""
    unique_pairs = set((data["channel_name"], data["package_name"]) for data in all_packages.values())

    # Run async description fetching
    descriptions = asyncio.run(get_descriptions(unique_pairs, reset_cache=reset_cache))

    # Assign descriptions to all packages
    for data in all_packages.values():
        key = (data["channel_name"], data["package_name"])
        web_description = descriptions.get(key, "Description not available")
        # Prefer web description if it's not an error or not found, else keep repodata description
        if web_description not in ["Description not found", "Error"]:
            data["description"] = web_description

    return all_packages


def save_to_json(data, output_file):
    """Save data to a JSON file"""
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Data saved to {output_file}")

## conda metadata to RAG memory
def load_json_file(file_path="conda_packages.json"):
    """Load JSON file into a Python dictionary."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"JSON file {file_path} not found.")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def preprocess_json_for_rag(json_data):
    """Convert JSON data into a list of Document objects for RAG."""
    documents = []
    for unique_key, pkg_info in json_data.items():
        # Extract relevant fields
        package_name = pkg_info.get("package_name", "")
        description = pkg_info.get("description", "No description available")
        version = pkg_info.get("version", "")
        channel = pkg_info.get("channel_name", "")
        platform = pkg_info.get("platform", "")
        # Create a text string for embedding (combine relevant fields)
        text = f"Package: {package_name}\nDescription: {description}\nVersion: {version}\nChannel: {channel}\nPlatform: {platform}"
        # Create metadata for filtering or additional context
        metadata = {
            "package_name": package_name,
            "version": version,
            "channel": channel,
            "platform": platform,
            "unique_key": unique_key
        }
        # Create a Document object
        doc = {
            'id': unique_key,
            'content': text,
            'metadata': metadata
        }
        documents.append(doc)
    return documents

def load_into_rag_memory(documents, chroma_db, collection_name="conda_packages"):
    """Load documents into AutoGen's RAG memory using Chroma."""
    # Initialize Chroma vector store
    # Add documents to the vector store
    #chroma_db.add(documents)
    for conda_doc in tqdm(documents):
        asyncio.run(chroma_db.add(MemoryContent(content=conda_doc['content'],
                                                metadata=conda_doc['metadata'],
                                                mime_type=MemoryMimeType.TEXT)))
    logger.info(f"Added {len(documents)} documents to RAG memory.")
    return chroma_db



def main():
    import logging
    from autogen_core.memory import MemoryMimeType

    logger = logging.getLogger(__name__)

    # Define channels to crawl (using Tsinghua mirrors for speed)
    channels = [
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main",
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge",
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/bioconda",
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch",
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r",
        "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/fastai",
        # Add more channels if needed
    ]

    # Define platforms
    platforms = ["linux-64", "osx-64", "osx-arm64", "linux-aarch64", "noarch"]

    # Crawl basic package info
    #packages = crawl_conda_packages(channels, platforms)

    # Add descriptions, reset cache to force re-fetching
    #packages = add_descriptions(packages, reset_cache=True)

    # Save to JSON file
    #save_to_json(packages, os.environ["CONDA_META_DATABASE"])

    conda_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="conda_metadata",
            persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen.conda_meta"),
            k=3,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
        )
    )

    print(f"RAG memory for f{os.environ.get('CONDA_META_DATABASE')}.")
    json_data = load_json_file(os.environ.get('CONDA_META_DATABASE'))
    documents = preprocess_json_for_rag(json_data)
    conda_memory_pubmed = load_into_rag_memory(documents, conda_memory, collection_name="conda_packages")

    print("Conda package metadata loaded into RAG memory.")

    conda_memory_pubmed.dump_component().model_dump_json()

    # close
    conda_memory_pubmed.close()



if __name__ == "__main__":
    os.environ["CONDA_META_DATABASE"] = "conda_packages.json"
    main()