import asyncio
import os
import json
import json
import sys
import time

import requests
from autogen_agentchat.ui import Console
from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient
from bs4 import BeautifulSoup
import git
import os
import subprocess

from sympy.codegen.ast import continue_
from tqdm import tqdm
from gitingest import ingest
from gitingest import ingest_async



def nf_list(path: str, load_json: bool = True):
    """List all Nextflow scripts in a given directory."""
    ## run shell command `nf-core list`
    # first check nf-core is installed
    if os.system("which nf-core") != 0:
        raise EnvironmentError("nf-core is not installed. Please install nf-core <pip install nf-core> to use this function.")
    if os.system("which nextflow") != 0:
        raise EnvironmentError("Nextflow is not installed. Please install Nextflow <conda install bioconda::nextflow> to use this function.")

    working_dir = os.getcwd()

    cmd = f"nf-core list --json > {working_dir}/{path}"

    if os.system(cmd) != 0:
        raise RuntimeError(f"Error running nf-core list command. {cmd}")

    ### fix json file error
    with open(path) as f:
        data = f.readlines()
    export_lines = ""
    desc_line = False
    for line in data:
        ## if this is a single line (have four \" in the line), skip
        if line.count('\"') %2 == 0 and line.count('\"') > 0:
            if desc_line:
                desc_line = False
            ## export_lines has '\n'?
            if not export_lines.endswith("\n"):
                export_lines += "\n"
            export_lines += line
            continue
        if line.count('\"') %2 != 0 or 'description' in line or desc_line:
            ## strip last character
            desc_line = True
            line = line[0:len(line)-1]
            export_lines += line
            continue
        export_lines += line
    print(export_lines[1:10])
    with open(path, "w") as f:
        f.write(export_lines)

    if load_json:
        with open(path, "r") as f:
            data = json.load(f)
        return data

    return None

def get_pipeline_readme(pipline_meta: dict, work_dir: str):
    """Get the README.md file from a Nextflow pipeline GitHub repository."""
    # Clone the repository to a temporary directory
    repo_name = pipline_meta["full_name"]
    pipeline_name = pipline_meta["name"]
    readme_file_name = pipline_meta["releases"][0]['doc_files']
    repo_tag = pipline_meta["releases"][0]['tag_name']
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)
    ## clone only the specific branch
    if not os.path.exists(f"{work_dir}/{pipeline_name}"):
        print(f"Cloning https://github.com/{repo_name} into {work_dir}/{pipeline_name}")
        git.Repo.clone_from(f"https://github.com/{repo_name}", f"{work_dir}/{pipeline_name}", branch=repo_tag, depth=10)
    else:
        print(f"Repository {repo_name} already exists in {work_dir}/{pipeline_name}, pulling latest changes.")
        pass
        #repo = git.Repo(f"{work_dir}/{pipeline_name}")
        #repo.remotes.origin.pull()

    return f"{work_dir}/{pipeline_name}"


def clone_snakemake_workflows(local_dir="./snakemake-workflows-repos", org="snakemake-workflows"):
    """
    Clones all repositories from the snakemake-workflows GitHub organization to a local directory.

    Args:
        local_dir (str): Local directory to store cloned repositories.
        org (str): GitHub organization name.

    Returns:
        list: List of local paths to the cloned repositories, or empty list if cloning fails.
    """
    # List to store paths of cloned repositories
    cloned_paths = []

    # GitHub API URL for organization repositories
    api_url = f"https://api.github.com/orgs/{org}/repos"

    try:
        # Create local directory if it doesn't exist
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)

        # Fetch repository list from GitHub API
        response = requests.get(api_url)
        response.raise_for_status()  # Raise exception for bad status codes
        repos = response.json()

        # Clone each repository
        for repo in repos:
            clone_url = repo["clone_url"]
            repo_name = repo["name"]
            repo_path = os.path.join(local_dir, repo_name)
            print(f"Cloning {repo_name} to {repo_path}...")
            result = subprocess.run(
                ["git", "clone", "https://ghfast.top/" + clone_url, repo_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                cloned_paths.append(os.path.abspath(repo_path))
            else:
                print(f"Failed to clone {repo_name}: {result.stderr}")

        print(f"All repositories cloned successfully to {local_dir}!")
        return cloned_paths

    except requests.RequestException as e:
        print(f"Error fetching repository list: {e}")
        return []
    except subprocess.SubprocessError as e:
        print(f"Error during cloning: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []

async def nf_list_to_chroma(nf_data:dict, chroma_db):
    """Ingest Nextflow pipeline data, split to chunks into ChromaDB."""
    for pipeline in tqdm(nf_data, desc="Processing pipelines"):
        print(f"Ingesting pipeline: {pipeline['name']}\n")
        summary, tree, content, full_name = pipeline["readme_summary"], pipeline["readme_tree"], pipeline["readme_content"], pipeline["full_name"]
        chunks = [content[i:i+1000] for i in range(0, len(content), 1000)]
        for i, chunk in enumerate(chunks):
            metadata = {
                "pipeline_name": pipeline["name"],
                "full_name": full_name,
                "description": pipeline["description"],
                "tag_name": pipeline["tag_name"],
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            try:
                await chroma_db.add(
                    MemoryContent(
                        content=chunk,
                        metadata=metadata,
                        mime_type=MemoryMimeType.TEXT,
                    )
                )
            except Exception as e:
                print(f"Failed to add chunk {i}, try with out metadata")
                metadata = {
                    "pipeline_name": pipeline["name"],
                    "chunk_index": i,
                }
                await chroma_db.add(
                    MemoryContent(
                        content=chunk,
                        metadata=metadata,
                        mime_type=MemoryMimeType.TEXT,
                    )
            )

    return chroma_db


if __name__ == "__main__":
    nf_data = nf_list("nf_cores_meta.json", load_json=True)
    nf_data = nf_data['remote_workflows']
    #print(nf_data)
    print(f"Found {len(nf_data)} Nextflow pipelines from nf-core.")

    all_pipelines = {}
    for pipeline in tqdm(nf_data, desc="Processing pipelines"):
        try:
            pipeline_path = get_pipeline_readme(pipeline, work_dir="nf_cores_repos")
        except Exception as e:
            print(f"Error getting README for {pipeline['name']}: {e}")
            time.sleep(9)
            # try more one time
            pipeline_path = get_pipeline_readme(pipeline, work_dir="nf_cores_repos")
        summary, tree, content = ingest(pipeline_path, exclude_patterns = ['*.fasta', '*.fq', '*.bam', '*.gz', '*.vcf'])
        #summary, tree, content = ingest(pipeline_path)
        print(f"Pipeline: {pipeline['name']}, Summary: {summary}, tree nodes: {tree}, content items: {content}")
        result = {
            "name": pipeline['name'],
            "full_name": pipeline['full_name'],
            "description": pipeline['description'],
            "doc_files": pipeline['releases'][0]['doc_files'],
            "tag_name": pipeline['releases'][0]['tag_name'],
            "readme_summary": summary,
            "readme_tree": tree,
            "readme_content": content
        }
        all_pipelines[pipeline['name']] = result

    ## dump to json
    with open("nf_cores_pipelines_meta_text.json", "w") as f:
        json.dump(all_pipelines, f, indent=4)

    ## run snakemake-workflows clone
    snakemake_repos = clone_snakemake_workflows(local_dir="snakemake-workflows-repos", org="snakemake-workflows")
    print(f"Cloned {len(snakemake_repos)} Snakemake workflow repositories.")
    for repo_path in tqdm(snakemake_repos, desc="Processing Snakemake workflows"):
        summary, tree, content = ingest(repo_path, include_patterns = 'README.md')
        repo_name = os.path.basename(repo_path)
        print(f"Snakemake Workflow: {repo_name}, Summary: {summary}, tree nodes: {tree}, content items: {content}")
        result = {
            "name": repo_name,
            "full_name": f"snakemake-workflows/{repo_name}",
            "description": f"Snakemake workflow {repo_name} from snakemake-workflows GitHub organization.",
            "doc_files": "README.md",
            "tag_name": "N/A",
            "readme_summary": summary,
            "readme_tree": tree,
            "readme_content": content
        }
        all_pipelines[repo_name] = result

    import os
    import asyncio
    import subprocess
    from pathlib import Path

    from autogen_agentchat.agents import AssistantAgent


    import logging

    from autogen_core import EVENT_LOGGER_NAME
    import json

    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(EVENT_LOGGER_NAME)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.ERROR)

    # Set the proxy (adjust as needed)
    os.environ["HTTPS_PROXY"] = "http://172.21.176.1:1083"
    os.environ["ASK_EXEC"] = "TRUE"
    os.environ["MARKDOWN_RENDERER"] = "TRUE"

    os.environ['CONDA_META_DATABASE'] = ''
    os.environ['WORKFLOW_DATABASE'] = ''
    os.environ['USER_EXT_DATABASE'] = ''

    ASK_EXEC = os.environ.get("ASK_EXEC") == "TRUE"
    MARKDOWN_RENDERER = os.environ.get("MARKDOWN_RENDERER") == "TRUE"

    # Create a custom model client with function calling enabled
    custom_model_client = OpenAIChatCompletionClient(
        model="grok-3-mini-fast",
        base_url="https://api.x.ai/v1/",
        api_key="xai-BOIfL6K4hZYigWTQ6U6Uaoumy383e34dohxZAjYllq2HfOL8ECXQoGbK5g3EZ2zKEaqX1DwsgDJdrNbd",
        # Replace with actual API key
        # api_key="xai-wruPEbZKjFIuOOjNcph3GcLSnFLOHxIrFhjZHrSbAoyNUVB4MOYTrw4XEHQuizCSFZ42ibiKEcOM8J5u",
        max_tokens=131072,
        model_info={
            "vision": False,
            "function_calling": True,  # Enable function calling to support tool usage
            "json_output": False,
            "family": 'gpt-4o',
            "structured_output": True,
            "multiple_system_messages": True,
        },
    )

    # remove previous chromadb database
    if os.path.exists(os.path.join(str(Path.home()), ".chromadb_autogen.nfcore1")):
        subprocess.run(["rm", "-rf", os.path.join(str(Path.home()), ".chromadb_autogen.nfcore1")])

    nf_memory_pubmed = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="nf_cores_pipelines",
            persistence_path=os.path.join(str(Path.home()), ".all-MiniLM-embedding.chromadb_autogen.nfcore1"),
            k=15,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
                model_name="all-MiniLM-L6-v2"  # Use default model for testing all-MiniLM-L6-v2
            ),
        )
    )

    asyncio.run(nf_memory_pubmed.clear())

    logger.debug('Ingesting Nextflow pipeline data into ChromaDB...')
    nf_memory_pubmed = asyncio.run(nf_list_to_chroma(all_pipelines.values(), nf_memory_pubmed))

    assistant_agent = AssistantAgent(
        name="assistant_agent",
        model_client=custom_model_client,
        memory=[nf_memory_pubmed],
        system_message="""
            Your are a helpful scientific research assistant specialized in bioinformatics analysis and workflow development. You have access to a collection of Nextflow and Snakemake workflows for various bioinformatics tasks. When given a task, you should:
                1. Understand the user's requirements and the specific bioinformatics analysis they need to perform.
                2. Summary this topics
                3. software and resources
                3. write a guideline (never directly call any nf-core or snakemake pipeline) step by step include software and resource
                4. Provide the guideline as a markdown document.
                5. return 'I dont know' if you are not sure about the answer.
        """
    )

    stream = assistant_agent.run_stream(task="Whats is ABO phenotype?",)
    asyncio.run(Console(stream))

    nf_memory_pubmed.dump_component().model_dump_json()
