import os
import asyncio
import subprocess
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import TextMentionTermination, ExternalTermination
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool
from rich.box import MARKDOWN
from typing_extensions import Annotated
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

import chainlit as cl

import logging

from autogen_core import EVENT_LOGGER_NAME
import json
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.ERROR)

## import memory system
from pubmed.article_rag import pubmed_search_to_rag

# Set the proxy (adjust as needed)
os.environ["HTTPS_PROXY"] = "http://172.20.0.1:1083"
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
    api_key="xai-BOIfL6K4hZYigWTQ6U6Uaoumy383e34dohxZAjYllq2HfOL8ECXQoGbK5g3EZ2zKEaqX1DwsgDJdrNbd",  # Replace with actual API key
    #api_key="xai-wruPEbZKjFIuOOjNcph3GcLSnFLOHxIrFhjZHrSbAoyNUVB4MOYTrw4XEHQuizCSFZ42ibiKEcOM8J5u",
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

custom_model_client2 = OpenAIChatCompletionClient(
    model="grok-4-0709",
    base_url="https://api.x.ai/v1/",
    api_key="xai-BOIfL6K4hZYigWTQ6U6Uaoumy383e34dohxZAjYllq2HfOL8ECXQoGbK5g3EZ2zKEaqX1DwsgDJdrNbd",  # Replace with actual API key
    #api_key="xai-wruPEbZKjFIuOOjNcph3GcLSnFLOHxIrFhjZHrSbAoyNUVB4MOYTrw4XEHQuizCSFZ42ibiKEcOM8J5u",
    max_tokens=256000,
    model_info={
        "vision": False,
        "function_calling": True,  # Enable function calling to support tool usage
        "json_output": False,
        "family": 'gpt-4o',
        "structured_output": True,
        "multiple_system_messages": True,
    },
)

custom_model_client3 = OpenAIChatCompletionClient(
    model="grok-code-fast",
    base_url="https://api.x.ai/v1/",
    api_key="xai-BOIfL6K4hZYigWTQ6U6Uaoumy383e34dohxZAjYllq2HfOL8ECXQoGbK5g3EZ2zKEaqX1DwsgDJdrNbd",  # Replace with actual API key
    #api_key="xai-wruPEbZKjFIuOOjNcph3GcLSnFLOHxIrFhjZHrSbAoyNUVB4MOYTrw4XEHQuizCSFZ42ibiKEcOM8J5u",
    max_tokens=256000,
    model_info={
        "vision": False,
        "function_calling": True,  # Enable function calling to support tool usage
        "json_output": False,
        "family": 'gpt-4o',
        "structured_output": True,
        "multiple_system_messages": True,
    },
)
#custom_model_client = OpenAIChatCompletionClient(
#    model="gemini-2.0-flash",
#    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
#    api_key="AIzaSyBF65XDWQFbsKs0sDHGZpoLKknhzyQ8fYM",  # Replace with actual API key
#   #model_info={
#   #    "vision": False,
#   #    "function_calling": True,  # Enable function calling to support tool usage
#   #    "json_output": False,
#   #    "family": 'gpt-4o',
#   #    "structured_output": True,
#   #},
#)

# Define the command execution tool
def execute_command(command):
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True, executable="/bin/bash")
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"

def truncate_long_text(text: str, max_lines: int = 1000) -> str:
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    if total_lines <= 2 * max_lines:
        return text
    else:
        first_part = ''.join(lines[:max_lines])
        last_part = ''.join(lines[-max_lines:])
        truncated_lines = total_lines - 2 * max_lines
        indicator = f"\n---\n{truncated_lines} lines truncated\n---\n"
        if not MARKDOWN_RENDERER:
            return first_part + indicator + last_part
        else:
            return "```\n" + first_part + indicator + last_part + "\n```"

async def execute_command2(command: str) -> str:
    ## logger
    logger.info(f"Executing command: {command}")
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True, executable="/bin/bash")
        return truncate_long_text(result.stdout)
    except subprocess.CalledProcessError as e:
        return f"Error: {truncate_long_text(e.stderr)}"

@cl.on_message
async def execute_command3(command: str) -> str:
    logger.info(f"Executing command: {command}")
    if ASK_EXEC:
        res = await cl.AskActionMessage(
            content="Confirm command execution",
            actions=[
                cl.Action(name="continue", payload={"value": "continue"}, label="✅ Continue"),
                cl.Action(name="cancel", payload={"value": "cancel"}, label="❌ Cancel"),
            ],
        ).send()

        if res and res.get("payload").get("value") == "continue":
            await cl.Message(
                content="Continue! Executing command...",
            ).send()
        else:
            await cl.Message(
                content="Cancel!",
            ).send()
            return f"User cancelled command execution: {command}"
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash"
        )
        stdout, stderr = await process.communicate()
        stdout = stdout.decode('utf-8')
        stderr = stderr.decode('utf-8')
        ### TODO: print waiting time when executing command
        if process.returncode == 0:
            return truncate_long_text(stdout)
        else:
            return f"Error: {truncate_long_text(stderr)}"
    except Exception as e:
        return f"Error: {truncate_long_text(str(e))}"

### MEMORY SYSTEM
# https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html
from autogen_core.memory import ListMemory, MemoryContent, MemoryMimeType
user_memory = ListMemory()
async def add_to_memory(content: str, mime_type: MemoryMimeType = MemoryMimeType.TEXT, metadata: dict = {}):
    await user_memory.add(MemoryContent(content=content, mime_type=mime_type, metadata=metadata))

add_to_memory_func = FunctionTool(add_to_memory, description="Add content to memory")

### rebulid function to execute command with api
os.environ['WORK_DIR'] = '/mnt/data1/zhangjy/bioGen_test'
os.environ['API_URL'] = 'http://10.157.66.19:38000'
os.environ['API_KEY'] = '87ZKvHYGiscjjsXSfuzlNA4_IHjsAdPczO-SRyEhlpc'
import os
import requests
import time
import json

def execute_shell_command_via_api(command: str, project_id: str = None, work_dir: str = os.environ['WORK_DIR'], flag: bool = True, api_url: str = os.environ['API_URL'], timeout: int = None):
    """
    Executes a shell command via the API.

    :param command: The shell command to execute (str).
    :param project_id: The project ID (str).
    :param work_dir: The working directory (str).
    :param flag: If True, wait for completion and return result; if False, return task ID (bool).
    :param api_url: The base API URL (e.g., http://localhost:8000) (str).
    :param timeout: Optional timeout for the command in seconds (float or None).
    :return: Task ID if flag=False; output or error message if flag=True (str).
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY environment variable is not set.")

    # If project_id is None, check environment variable
    if project_id is None:
        project_id = os.getenv("PROJECT_ID")

    logger.info(f"Executing command: {command} with project_id: {project_id} in work_dir: {work_dir}")

    # 1. Check if API is running
    try:
        response = requests.get(api_url)
        if response.status_code != 200:
            raise ValueError("API is not running or unreachable.")
    except requests.RequestException as e:
        raise ValueError(f"API check failed: {str(e)}")

    # If project_id is still empty or not set, create a new project and set working directory
    if not project_id:
        headers = {
            "x-api-key": api_key
        }
        # Create new project
        create_endpoint = f"{api_url}/projects"
        try:
            response = requests.post(create_endpoint, headers=headers)
            response.raise_for_status()
            project_id = response.json()["project_id"]
        except requests.RequestException as e:
            raise ValueError(f"Failed to create project: {str(e)}")

        # Set working directory for the new project
        set_wd_endpoint = f"{api_url}/projects/{project_id}/set-working-dir"
        set_wd_body = {
            "working_dir": work_dir
        }
        try:
            response = requests.post(set_wd_endpoint, headers={**headers, "Content-Type": "application/json"}, json=set_wd_body)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ValueError(f"Failed to set working directory: {str(e)}")

        # Set the new project_id in the environment variable
        os.environ["PROJECT_ID"] = project_id

    # 2. Submit the task
    execute_endpoint = f"{api_url}/projects/{project_id}/execute"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key
    }
    body = {
        "command": command,
        "working_dir": work_dir
    }
    if timeout is not None:
        body["timeout"] = timeout

    try:
        response = requests.post(execute_endpoint, headers=headers, json=body)
        response.raise_for_status()
        result = response.json()
        task_id = result["id"]
    except requests.RequestException as e:
        raise ValueError(f"Failed to submit task: {str(e)}")

    if not flag:
        return task_id

    # 3. If flag=True, poll for completion
    status_endpoint = f"{api_url}/status/{task_id}"
    output_endpoint = f"{api_url}/history/{task_id}/output"
    poll_interval = 1  # seconds
    while True:
        try:
            status_response = requests.get(status_endpoint)
            status_response.raise_for_status()
            status = status_response.json()
            if not status["is_running"]:
                # Get output
                output_response = requests.get(output_endpoint)
                output_response.raise_for_status()
                output_data = output_response.json()
                full_output = output_data["output"]

                # Check for error
                if status["returncode"] != 0:
                    return truncate_output(f"Error when running: {command}.\noutput: \n{full_output}")

                return truncate_output(f"Successful running: {command}.\noutput:\n{full_output}")
        except requests.RequestException as e:
            raise ValueError(f"Polling failed: {str(e)}")

        time.sleep(poll_interval)

def truncate_output(output, max_lines=100):
    """
    Truncates output to first and last max_lines lines if too long.
    """
    lines = output.split('\n')
    if len(lines) <= 2 * max_lines:
        return output
    truncated = '\n'.join(lines[:max_lines]) + '\n...\n' + '\n'.join(lines[-max_lines:])
    return truncated

def list_files(directory: str) -> str:
    """
    Recursively list all files in the specified directory and its subdirectories,
    return the absolute path, size, and modification time of the files, output in JSON format.
    """
    file_list = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            file_size = os.path.getsize(file_path)
            modification_time = os.path.getmtime(file_path)
            file_list.append({
                "path": file_path,
                "size": file_size,
                "modification_time": modification_time
            })
    return json.dumps(file_list, indent=4)


def write_file(content: str, path: str, format: str='t', mode: str='w'):
    """
    Write the content to the file at the specified path and return whether it was successful.

    :param content: The content to write (str or bytes, depending on format)
    :param path: The file path
    :param format: The file format, default 't' (text), can be 'b' (binary)
    :param mode: The open mode, default 'w' (write)
    :return: True if successful, False if failed
    """
    full_mode = mode + format
    try:
        with open(path, full_mode) as f:
            f.write(content)
        return True
    except Exception:
        return False


import gzip
import os


def read_file_lines(path: str, line: int=10, tail: bool=False):
    """
    Read the specified number of lines from the start or end of a text file and return them.

    :param path: The file path
    :param line: Number of lines to read, default is 10
    :param tail: If True, read from the end; if False, read from the start (default)
    :return: List of lines if successful, or error message if the file is not text or gzip containing text
    """
    try:
        # Check if file is gzip
        if path.endswith('.gz'):
            with gzip.open(path, 'rt') as f:
                lines = f.readlines()
        else:
            # Check if file is text by attempting to read it as text
            with open(path, 'r') as f:
                lines = f.readlines()

        # Select lines based on tail parameter
        if tail:
            return lines[-line:] if line > 0 else []
        else:
            return lines[:line] if line > 0 else []

    except (UnicodeDecodeError, gzip.BadGzipFile):
        return "Error: File is not a valid text file or gzip-compressed text file"
    except FileNotFoundError:
        return "Error: File not found"
    except Exception as e:
        return f"Error: {str(e)}"


#execute_tool = Tool(name="execute_command", func=execute_command, description="Execute a Linux command and return the output.")
execute_tool = FunctionTool(execute_shell_command_via_api, description="execute a Linux command and return the output.")

## create pubmed agent memory manager
rag_memory_pubmed = ChromaDBVectorMemory(
    config=PersistentChromaDBVectorMemoryConfig(
        collection_name="pubmed_articles",
        persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen.pubmed"),
        k=3,  # Return top 3 results
        score_threshold=0.4,  # Minimum similarity score
    )
)

asyncio.run(rag_memory_pubmed.clear())


# pubmed_search_to_rag function tool
def pubmed_search_to_rag_call(keyword: str, max_results: int = 30):
    _ = pubmed_search_to_rag(keyword, rag_memory_pubmed, max_results)
    return 'Successfully searched PubMed and added results to internal memory.'
pubmed_search_to_rag_tool = FunctionTool(pubmed_search_to_rag_call, description="Search PubMed for articles related to a query and add the content to the agent's memory.")

# Define the agents
async def user_input_func(prompt: str, cancellation_token: CancellationToken | None = None) -> str:
    """Get user input from the UI for the user proxy agent."""
    try:
        response = await cl.AskUserMessage(content=prompt).send()
    except TimeoutError:
        return "User did not provide any input within the time limit."
    if response:
        return response["output"]  # type: ignore
    else:
        return "User did not provide any input."

conda_memory = ChromaDBVectorMemory(
    config=PersistentChromaDBVectorMemoryConfig(
        collection_name="conda_metadata",
        persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen.conda_meta"),
        k=3,  # Return top 3 results
        score_threshold=0.4,  # Minimum similarity score
    )
)

# if CONDA_META_DATABASE set and path exists, load conda metadata to memory
if os.environ.get('CONDA_META_DATABASE') and os.path.exists(os.environ.get('CONDA_META_DATABASE')):
    ## load jsonl file to memory
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
            doc = Document(
                id=unique_key,
                content=text,
                metadata=metadata
            )
            documents.append(doc)
        return documents

    def load_into_rag_memory(documents, chroma_db, collection_name="conda_packages"):
        """Load documents into AutoGen's RAG memory using Chroma."""
        # Initialize Chroma vector store
        # Add documents to the vector store
        #chroma_db.add(documents)
        for conda_doc in documents:
            asyncio.run(chroma_db.add(conda_doc))
        logger.info(f"Added {len(documents)} documents to RAG memory.")
        return chroma_db

    # workflow
    json_data = load_json_file(os.environ.get('CONDA_META_DATABASE'))
    documents = preprocess_json_for_rag(json_data)
    conda_memory_pubmed = load_into_rag_memory(documents, conda_memory, collection_name="conda_packages")

## if USER_EXT_DATABASE set and path exists, load user ext to memory
if os.environ.get('USER_EXT_DATABASE') and os.path.exists(os.environ.get('USER_EXT_DATABASE')):
    def pdfToText(pdf_file):
        pdf = PdfReader(pdf_file)
        text = ''
        for page in pdf.pages:
            text += page.extract_text()
        return text
    ## find all pdf; txt; markdown files in the path
    database_path = os.environ.get('USER_EXT_DATABASE')
    ## use a tupple to store all file path (file_path, file_type)
    file_list = []
    for root, dirs, files in os.walk(database_path):
        for file in files:
            if file.endswith('.pdf') or file.endswith('.txt') or file.endswith('.md') or file.endswith('.markdown') or file.endswith('.text') or file.endswith('.html'):
                file_list.append((os.path.join(root, file), file.split('.')[-1]))
    ## for each file, read the content and add to memory
    def _split_text(self, text: str) -> List[str]:
        """Split text into fixed-size chunks."""
        chunks: list[str] = []
        # Just split text into fixed-size chunks
        for i in range(0, len(text), self.chunk_size):
            chunk = text[i : i + self.chunk_size]
            chunks.append(chunk.strip())
        return chunks
    for file_path, file_type in file_list:
        try:
            content = None
            if file_type == 'pdf':
                content = pdfToText(file_path)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.readlines()
                    content = '\n'.join(content)
            ## add to rag_memory_pubmed
            if content is None:
                logger.debug("Content is None.")
                continue
            chunks = _split_text(content)
            total_chunks = 0
            for i, chunk in enumerate(chunks):
                doc = MemoryContent(
                    content=chunk,
                    mime_type=MemoryMimeType.TEXT,
                    metadata={"source": file_path, "chunk_index": i}
                )
                asyncio.run(rag_memory_pubmed.add(doc))
                total_chunks += 1
            logger.info(f"Added {total_chunks} chunks from file {file_path} to RAG memory.")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")


if __name__ == "__main__":
    input_func = input
else:
    input_func = user_input_func
user_proxy = UserProxyAgent("user_proxy")
planning_agent = AssistantAgent(
    "PlanningAgent",
    description="An agent for planning tasks, this agent should be the first to engage when given a new task.",
    model_client=custom_model_client,
    memory=[user_memory, rag_memory_pubmed],
    system_message="""
    You are a planning agent.
    Your job is to break down complex tasks into smaller, manageable subtasks.
    Your team members are:
        user_proxy: Asks users about their needs.
        user_chat: simplify process user needs from @UserProxyAgent or other.
        file_agent: list files in a specified directory and/or sub directories, write file or read text file with specific path.
        query_agent: Understand user Linux command requests and requests clarification when necessary.
        command_generator_agent: A knowledgeable assistant that generates precise Linux commands based on user requests.
        code_generator_agent: A skilled assistant that generates accurate, clear, and reliable code in Python, R, C++, or other specified programming languages based on user requests.
        safety_checker_agent: A safety-conscious assistant that reviews the safety of Linux commands.
        system_check_agent: A knowledgeable assistant that generates precise Linux commands to check the system configuration.
        executor_agent: An assistant that only executes safe Linux commands.
        web_surfer_agent: An Multimodal WebSurfer
        bio_micromamba_env_agent: A knowledgeable assistant that generates precise micromamba commands to micromamba environment for specific tasks.
        manager_mem_agent: A memory manager agent that updates the memory based on user-assistant exchanges.
        pubmed_rag_agent: A agent that searches PubMed for relevant articles and adds them to Your RAG memory.
        
    
    You need to be aware that you may have a limited context length. To maintain focus on the task during long conversation, update necessary memory via @manager_mem_agent. 

    You only plan and delegate tasks - you do not execute them yourself.
    All commands must be safety check with safety_checker_agent
    Only assigning one task one time
    
    Create a separate environment for each subtask to avoid potential conflicts if need.
    
    

    When assigning tasks, use this format:
    1. <agent> : <task>

    After all tasks are complete, summarize the findings and end with "TERMINATE" twice with out space.
    DONT OUTPUT string or thought with "TERMINATE" IF YOU DONT WANT end the process.
    """,
)
#file_agent: list files in a specified directory and sub directories, write file or read text file with specific path.
user_chat = AssistantAgent(
    "user_chat",
    model_client=custom_model_client,
    description="An assistant who asks users about their needs",
    system_message="You are an assistant inquiring about user needs. The user's needs should be related to the operation of the bioinformatics analysis. \
                        No matter what language the user uses, you should use English \
                        You need to reject irrelevant requests, \
                        Otherwise, pass the request to the query agent by saying '@query_agent please future process the following request: [request]'."
)
query_agent = AssistantAgent(
    "query_agent",
    model_client=custom_model_client,
    description="An assistant that understands user Linux command requests and requests clarification when necessary.",
    system_message="You are an assistant that understands user bioinformatics analysis requests. \
                        If the request is unclear or needs more details, please request clarification. \
                        Otherwise, pass the request directly",
)

system_check_agent = AssistantAgent(
    "command_generator_agent",
    model_client=custom_model_client2,
    description="A knowledgeable assistant that generates precise Linux commands to check the system configuration.",
    system_message="You are an assistant that generates precise Linux commands to check the system configuration, such as whether certain packages have been installed and the system version. \
                        When other agents asks you to generate a command, \
                        Try to ensure that commands are executed silently as much as possible, because users may not be able to interact with the terminal, \
                        please generate the command",
)

bio_micromamba_env_agent = AssistantAgent(
    "bio_micromamba_env_agent",
    model_client=custom_model_client2,
    memory=[user_memory, rag_memory_pubmed, conda_memory],
    description="A knowledgeable assistant that generates precise micromamba commands to micromamba environment for specific tasks.",
    system_message="You are an assistant that generates precise micromamba commands to micromamba environment for specific tasks, such as install necessary packages. \
                        ENSURE that commands are executed silently as much as possible, because users may not be able to interact with the terminal, \
                        You can generate more than one command (one command one line), other necessary (such as pip) is also acceptable, \
                        please generate the command",
)

command_generator_agent = AssistantAgent(
    "command_generator_agent",
    model_client=custom_model_client2,
    memory=[user_memory, rag_memory_pubmed, conda_memory],
    description="A knowledgeable assistant that generates precise Linux commands based on user requests.",
    system_message="You are an assistant that generates precise Linux commands based on user requests. \
                        When @query_agent asks you to generate a command, \
                        std.error and std.out will be process automatically, so dont need to redirect it if unnecessary. \
                        ENSURE  that commands are executed silently as much as possible, because users may not be able to interact with the terminal, \
                        if you want run commands in micromamba environment, use `micromamba run` instead of `micromamba activate`. \
                        please generate the command and say '@safety_checker_agent please check this command: [command]'.",
)

code_generator_agent = AssistantAgent(
    "code_generator_agent",
    model_client=custom_model_client3,
    memory=[user_memory, rag_memory_pubmed, conda_memory],
    description="A skilled assistant that generates accurate, clear, and reliable code in Python, R, C++, or other specified programming languages based on user requests.",
    system_message="You are an assistant that generates accurate, clear, and reliable code with the programming language specified by the user (e.g., Python, R, C++). \
                   When other agents asks you to generate code, ensure the code is well-structured, includes clear and concise comments explaining functionality, \
                   and adheres to best practices for the specified language. \
                   If no language is specified, ask the user to clarify the desired programming language. \
                   Provide the complete code block and say '[code block]' at the end of the response. \
                   If you think the code needs to be split into multiple related files, provide it in the format below \
                   <path/file_a.py>: <code block> \\n <path/file_b.py>: <code block> \\n ... \
                   DONT WARPER the code with shell command. \
                   ",
)

safety_checker_agent = AssistantAgent(
    "safety_checker_agent",
    model_client=custom_model_client,
    description="A safety-conscious assistant that reviews the safety of Linux commands.",
    system_message="You are an assistant that reviews the safety of Linux commands. \
                        When @command_generator_agent asks you to check a command, please check it. \
                        If the command is safe, say 'command is safe: [command]'. \
                        If it is not safe, say 'command is not safe: [reason]'.",
)

executor_agent = AssistantAgent(
    "executor_agent",
    model_client=custom_model_client,
    tools=[execute_tool],
    description="An assistant that only executes safe Linux commands.",
    system_message="You have access to the 'execute_command' tool. When @safety_checker_agent says 'command is safe: [command]', use the 'execute_command' tool to execute [command] and report the output (if has). If @safety_checker_agent says 'command is not safe', say 'Command not executed due to safety concerns', then say 'TERMINATE'.",
)

web_surfer_agent = MultimodalWebSurfer(
        "WebSurfer",
        model_client=custom_model_client,
    )


file_agent = AssistantAgent(
    name="file_lister",
    model_client=custom_model_client,
    tools=[execute_tool],
    system_message="You are an assistant who can list files in a directory, write files or read text file. \
                        generate a shell command and call execute_command tool to execute the command to finish your task. \
                        When you receive a task to list directory files, use the list_files tool to return the file properties in JSON format. \
                        When you receive a task to write a file, use the write_file tool, Pay attention to properly handling line breaks.. When you receive a task to read a text file, only read and output first and tail 100 line if file > 1Kb.",
)

file_read_agent = AssistantAgent(
    name="FileProcessor",
    model_client=custom_model_client,  # Adjust as needed
    memory=[user_memory, rag_memory_pubmed],
    system_message="""
You are a file processing agent designed to handle file inputs using shell commands. When given a file path, follow these steps:
1. Check if the file exists by running `execute_tool('test -f <file_path>')`. If the command fails (returns non-zero exit code), respond with "File does not exist."
2. If the file exists, determine its type by running `execute_tool('file -b <file_path>')`.
3. Based on the output (case-insensitive):
   - If it contains 'text', treat it as a text file and run `execute_tool('head -n 100 <file_path>')` to get the first 100 lines.
   - For other formats, try to open it with shell tools and obtain the first 100 lines as text. However, note that if the required tool error because it is not installed, do not attempt to install it but report the error directly
   - For any other output, respond with "File type not supported."
4. If the command to retrieve content succeeds (output does not start with "Error:"), use the output to generate a summary and description of the content using your language model.
5. If the command fails (output starts with "Error:"), respond with the error message (e.g., "Error: samtools not found" if samtools is unavailable).
""",
    tools=[execute_tool],
)

manager_mem_agent = AssistantAgent(
    name ="manager_mem_agent",
    model_client=custom_model_client,
    memory=[user_memory],
    tools=[add_to_memory_func],
    system_message="""
       "You are a memory updater agent. Your role is to analyze user-assistant exchanges contents"
        "and decide if a short summary should be added to the memory. "
        "Output a concise summary only if new important information is present; "
        "otherwise, output exactly 'No update'."
    """,
)


## a manager agent to manage pubmed memory
manager_pubmed_mem_agent = AssistantAgent(
    name ="manager_pubmed_mem_agent",
    model_client=custom_model_client,
    memory=[rag_memory_pubmed],
    tools=[pubmed_search_to_rag_tool],
    system_message="""
       You are a pubmed memory manager agent. Determine a concise keyword, Call pubmed_search_to_rag_tool to search pubmed for articles related to a query and add the content to the agent's memory.
       """,
)



# Set the termination condition
termination = TextMentionTermination("TERMINATETERMINATE")
external_termination = ExternalTermination()

# Create the group chat
group_chat = RoundRobinGroupChat(
    [user_proxy, user_chat, query_agent, command_generator_agent, safety_checker_agent, web_surfer_agent, executor_agent, manager_mem_agent],
    termination_condition=termination | external_termination
)


selector_prompt = """Select an agent to perform task.

{roles}

Current conversation context:
{history}

Read the above conversation, then select an agent from {participants} to perform the next task.
Make sure the planner agent has assigned tasks before other agents start working.
Only select one agent each time.
"""

tasks = """
    You are a knowledgeable bioinformatics assistant. You run in a Linux environment. \
    Assume workdir is {work_dir_env}, \
    You need to understand the user's requirements about specific Bioinformatics tasks, \
    first call @user_proxy to get user input, \
    check the legitimacy of the requirements, and implement them through appropriate and secure Linux commands. \
    If necessary, before fulfilling the user's requirements, you can decide to ask @system_check_agent to generate command to check the system or confirm some information (eg: software version). These commands must also undergo security checks. \
    @bio_micromamba_env_agent could help prepare micromamba env, all new envs should store at [work_dir]/envs \
    @file_agent could help you list file in specific path and subdir as json format, \
    When a certain method fails, you need to try different methods and share the information with team members you will asked. \
    If multiple attempts fail, require user's help or terminate the process. You also can search web by @web_surfer_agent,\
    please note that you cannot assume or perform any operations as superusers. \
    You need to be aware that you may have a limited context length. To maintain focus on the task during long conversation, update necessary memory via @manager_mem_agent.  \
    Only one agents called each time
""".format(work_dir_env = os.environ['WORK_DIR'])

selector_team = SelectorGroupChat(
    [planning_agent, user_proxy, user_chat, query_agent, command_generator_agent, safety_checker_agent, executor_agent, web_surfer_agent, file_agent, manager_mem_agent, manager_pubmed_mem_agent],
    model_client=custom_model_client,
    termination_condition=termination,
    selector_prompt=selector_prompt,
    allow_repeated_speaker=True,  # Allow an agent to speak multiple turns in a row.
)

async def main():
    await selector_team.reset()
    await Console(selector_team.run_stream(task=tasks))
    # Close the model client
    external_termination.set()
    #await selector_team.close()


def get_team(
    user_input_func2,
) -> SelectorGroupChat:
    user_proxy = UserProxyAgent('user_proxy', input_func=user_input_func2)
    selector_team = SelectorGroupChat(
    [planning_agent, user_proxy, user_chat, query_agent, command_generator_agent, safety_checker_agent, executor_agent, file_agent, manager_mem_agent, manager_pubmed_mem_agent],
    model_client=custom_model_client,
    termination_condition=termination,
    selector_prompt=selector_prompt,
    allow_repeated_speaker=False,  # Allow an agent to speak multiple turns in a row.
)
    return selector_team


if __name__ == "__main__":
    asyncio.run(main())