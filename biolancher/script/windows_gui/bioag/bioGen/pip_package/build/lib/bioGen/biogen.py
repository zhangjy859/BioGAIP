import os
import asyncio
import subprocess
from pathlib import Path
import base64
import gzip
import threading
from importlib.resources import files


from autogen_agentchat.conditions import TextMentionTermination, ExternalTermination
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

import chainlit as cl

import logging

from autogen_core import EVENT_LOGGER_NAME
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.ERROR)

## import memory system
from bioGen.pubmed.article_rag import pubmed_search_to_rag
from bioGen.config.load_config import *

# Set the proxy (adjust as needed)
#os.environ["HTTPS_PROXY"] = "http://172.27.176.1:1083"

if __package__ is None:
    os.environ['SYSTEM_CONFIG_PATH'] = os.environ.get('SYSTEM_CONFIG_PATH', '/config')
else:
    os.environ['SYSTEM_CONFIG_PATH'] = os.environ.get('SYSTEM_CONFIG_PATH', files(__package__).joinpath('config').__str__())
system_yaml=os.path.join(os.environ['SYSTEM_CONFIG_PATH'],'system_config.yaml')
config_yaml=os.path.join(os.environ['SYSTEM_CONFIG_PATH'],'config.yaml')
agent_yaml=os.path.join(os.environ['SYSTEM_CONFIG_PATH'],'agent_config.yaml')
tool_yaml=os.path.join(os.environ['SYSTEM_CONFIG_PATH'],'tool_config.yaml')

if os.getenv('SYSTEM_CONFIG_YAML_PATH', None):
    system_yaml = os.getenv('SYSTEM_CONFIG_YAML_PATH')

if os.path.exists(config_yaml):
    config = yaml.load(open(config_yaml), Loader=yaml.FullLoader)
else:
    config = {}

config_bioAG = config.get('bioAG', {})
config_bioWorker = config.get('bioWorker', {})

os.environ["ASK_EXEC"] = config_bioAG.get('ASK_EXEC', 'False')
os.environ["MARKDOWN_RENDERER"] = config_bioAG.get('MARKDOWN_RENDERER', 'True')

#os.environ['CONDA_META_DATABASE'] = ''
#os.environ['WORKFLOW_DATABASE'] = ''
os.environ['CONDA_META_DATABASE'] = config_bioAG.get('CONDA_META_DATABASE', '/data/conda_meta')
os.environ['WORKFLOW_DATABASE'] = config_bioAG.get('WORKFLOW_DATABASE', '/data/pipelines_meta')
#os.environ['USER_EXT_DATABASE'] = '/mnt/e/software/bioGen/test_dir/Literature/ABO Phenotype'
os.environ['USER_EXT_DATABASE'] = config_bioAG.get('USER_EXT_DATABASE', '/data/user_ext')


os.environ['WORK_DIR'] = config_bioWorker.get('WORK_DIR', '/data/work_dir')
#os.environ['WORK_DIR'] = '/home/server/bio_test/test1'
if 'API_URL' in config_bioAG:
    os.environ['API_URL'] = config_bioAG.get('API_URL', 'http://localhost:8000')
if 'API_KEY' in config_bioAG:
    os.environ['API_KEY'] = config_bioAG.get('API_KEY', '')

SYSTEM_CONFIG_PATH = system_yaml
sys_config = yaml.load(open(SYSTEM_CONFIG_PATH), Loader=yaml.FullLoader)

## tool set
if os.getenv('SKIP_CUSTOM_TOOL') != 'true':
    tools_set1 = load_tools(sys_config)
    if os.path.exists(tool_yaml):
        tool_config = yaml.load(open(tool_yaml), Loader=yaml.FullLoader).get('tools', {})
        tools_set2 = load_tools(tool_config)
    else:
        tools_set2 = {}
    # merge two tool sets
    custom_tools = {**tools_set1, **tools_set2}
else:
    custom_tools = {}
## remote tool set
remote_tool_loaded = False
if os.getenv('SKIP_REMOTE_CUSTOM_TOOL') != 'true':
    tools_set1 = sys_config.get('remote_tools', {})
    print('===========start Debug==============')
    print(tool_yaml)
    if os.path.exists(tool_yaml):
        tools_set2 = yaml.load(open(tool_yaml), Loader=yaml.FullLoader).get('remote_tools', {})
    print('toolset2:', tools_set2)
    remote_tool_dict = {**tools_set1, **tools_set2}
    print('remote_tool_dict:', remote_tool_dict)
    print('get remote info', str(len(remote_tool_dict.values())))
    print('================= debug end ==========')
    if len(remote_tool_dict.values()) > 0: 
        print('get remote info', str(len(remote_tool_dict.values())))
        remote_tool_dict = {'remote_tools': remote_tool_dict}
        remote_tool_loaded = True
        remote_tool_description = generate_remote_tool_description(remote_tool_dict)
        print(remote_tool_description )
        remote_tool_detail = extract_remote_tools_detail(remote_tool_dict)
    else: 
        remote_tool_loaded = False

    
## load agents config
use_external_agents_config = False
if 'agents' not in sys_config and os.path.exists(agent_yaml):
    agents_config = yaml.load(open(agent_yaml), Loader=yaml.FullLoader)
    ## combine dict
    sys_config = {**sys_config, **agents_config}
    use_external_agents_config = True
if 'model_clients' not in sys_config and not os.path.exists(agent_yaml):
    raise FileNotFoundError('Agent configuration file not found')
if 'model_clients' not in sys_config:
    raise ValueError(f'No model_clients found in system configuration: {sys_config}')
default_model_name = sys_config.get('default_model')
content_summary_model_name = sys_config.get('content_summary_model', None)
if not content_summary_model_name:
    content_summary_model_name = default_model_name

ASK_EXEC = os.environ.get("ASK_EXEC").lower == "true"
MARKDOWN_RENDERER = os.environ.get("MARKDOWN_RENDERER") == "TRUE"
SKIP_MODEL_CONTEXT = os.environ.get("SKIP_MODEL_CONTEXT", "False").lower() == "true"
SKIP_MODEL_CONTEXT_CONFIG = sys_config.get("skip_params_model_context", False)
SKIP_MODEL_CONTEXT = SKIP_MODEL_CONTEXT or SKIP_MODEL_CONTEXT_CONFIG
os.environ['SKIP_MODEL_CONTEXT'] = "True" if SKIP_MODEL_CONTEXT else "False"

### load model
model_clients = load_model_clients(SYSTEM_CONFIG_PATH)
logger.info(f"Loaded model clients: {len(list(model_clients.keys()))}")
if default_model_name not in model_clients:
    raise Exception(f"Default model name '{default_model_name}' not in model config.")
default_model = model_clients[default_model_name]
content_summary_model = model_clients[content_summary_model_name]


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

#@cl.on_message
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
                content="Cancel! Ask user more details",
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
#user_memory2 = ChromaDBVectorMemory(
#        config=PersistentChromaDBVectorMemoryConfig(
#            collection_name="user_memory",
#            persistence_path='~/.cache',
#            k=2,  # Return top k results
#            score_threshold=0.4,
#            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
#                model_name="all-MiniLM-L6-v2"
#            ),
#        )
async def add_to_memory(content: str, mime_type: MemoryMimeType = MemoryMimeType.TEXT, metadata: dict = {}):
    await user_memory.add(MemoryContent(content=content, mime_type=mime_type, metadata=metadata))

add_to_memory_func = FunctionTool(add_to_memory, description="Add content to memory")

### rebulid function to execute command with api
import os
import requests
import time
import json

_exec_states = {}

#@cl.on_message
async def execute_shell_command_via_api(command: str, project_id: str = None, work_dir: str = os.getenv('WORK_DIR'), flag: bool = True, api_url: str = os.environ.get('API_URL', ''), timeout: int = None, max_lines: int = int(os.environ.get('MAX_LINES', 10))):
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

    api_url = api_url or os.environ.get("API_URL")

    # If project_id is None, check environment variable
    if project_id is None:
        if 'st' in globals():
            project_id = st.session_state.get("PROJECT_ID", None)
        else: 
            project_id = os.getenv("PROJECT_ID")

    if not work_dir:
        work_dir = os.getcwd()

    logger.info(f"Executing command: {command} with project_id: {project_id} in work_dir: {work_dir}")
    
    if command.strip() == "" and project_id:
        return project_id
    
    if 'ls' in command or "ls" in command:
        max_lines = max(max_lines, 100)

    # Retirement function
    if ASK_EXEC and __name__ != '__main__':
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
                content="Cancel! Ask user more details",
            ).send()
            return f"User cancelled command execution: {command}"

    # 1. Check if API is running
    try:
        response = requests.get(api_url)
        if response.status_code != 200:
            raise ValueError("API is not running or unreachable.")
    except requests.RequestException as e:
        raise ValueError(f"API check failed: {str(e)}")

    # If project_id is still empty or not set, create a new project and set working directory
    if not project_id or project_id.strip() == "":
        logger.info("No project_id provided. Creating a new project.")
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
        print(f"Setting working directory to {work_dir} for project {project_id}")
        try:
            response = requests.post(set_wd_endpoint, headers={**headers, "Content-Type": "application/json"}, json=set_wd_body)
            response.raise_for_status()
        except requests.RequestException as e:
            #raise ValueError(f"Failed to set working directory: {str(e)}")
            logger.error(f"Error: Failed to set working directory: {str(e)}")

        # Set the new project_id in the environment variable
        os.environ["PROJECT_ID"] = project_id

    if project_id not in _exec_states:
        _exec_states[project_id] = {'count': 0, 'cond': asyncio.Condition()}
    state = _exec_states[project_id]
    state['count'] += 1

    try:
        ## preprocess for command
        ## if command line number > 10, use 'bash -c "command"'
        #if command.count('\n') >= 10:
        #    command = f'bash -c "{command}"'

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
            #raise ValueError(f"Failed to submit task: {str(e)}")
            return f"Failed to submit task: Error: ```\n{str(e)} \n```, retry may work"

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

                    ## if str length of full_output < 3:
                    if len(full_output) < 3:
                        full_output = "<No output> " + full_output

                    # Check for error
                    if status["returncode"] != 0:
                        return truncate_output(f"Error when running: {command}.\noutput: \n{full_output}")

                    return truncate_output(f"Successful running: {command}.\noutput:\n{full_output}")
            except requests.RequestException as e:
                #raise ValueError(f"Polling failed: {str(e)}")
                logger.error(f"Failed to get status: {str(e)}")
                return f"Failed to get status: Error: ```\n{str(e)} \n```, retry may work"

            await asyncio.sleep(poll_interval)
    finally:
        async with state['cond']:
            state['count'] -= 1
            if state['count'] == 0:
                state['cond'].notify_all()
            else:
                await state['cond'].wait()
        
## fix the libmamba Could not open lockfile error
def rm_lockfiler_libmamba(input: str):
    if "libmamba" in input and "Could not open lockfile" in input:
        # remove the line with libmamba lockfile error
        lines = input.split('\n')
        new_lines = [line for line in lines if "Could not open lockfile" not in line]
        return '\n'.join(new_lines)
    return input
        
_exec_states_sync = {}
_exec_sync_lock = threading.Lock()

def execute_via_api(command: str, project_id: str = None, working_dir: str = None, script_type: str = None, interpreter: str = None, conda_env: str = None, wait: bool = True, api_url: str = None, timeout: float = None, max_lines: int = int(os.environ.get('MAX_LINES', 10))):
    """
    Executes a command or script via the API.

    :param command: The command or script content to execute (str).
    :param project_id: The project ID (str, optional).
    :param working_dir: The working directory (str, optional).
    :param script_type: The script type ('python', 'r', 'perl') (str, optional).
    :param interpreter: Path to interpreter (str, optional).
    :param conda_env: Conda environment name or prefix path (str, optional).
    :param wait: If True, wait for completion and return output; if False, return task ID (bool).
    :param api_url: The base API URL (str, optional).
    :param timeout: Optional timeout in seconds (float, optional).
    :return: Task ID if wait=False; output or error message if wait=True (str).
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not set")

    api_url = api_url or os.getenv("API_URL")
    if not api_url:
        raise ValueError("API_URL not set")

    if working_dir is None:
        working_dir = os.getenv("WORK_DIR") or os.getcwd()

    if project_id is None:
        project_id = os.getenv("PROJECT_ID")

    try:
        response = requests.get(api_url)
        response.raise_for_status()
    except Exception as e:
        raise ValueError(f"API not reachable: {str(e)}")
    
    if "ls" in command or "ll" in command:
        max_lines = max(max_lines, 100)

    if not project_id:
        headers = {"x-api-key": api_key}
        response = requests.post(f"{api_url}/projects", headers=headers)
        response.raise_for_status()
        project_id = response.json()["project_id"]

        wd_body = {"working_dir": working_dir}
        response = requests.post(f"{api_url}/projects/{project_id}/set-working-dir", headers={**headers, "Content-Type": "application/json"}, json=wd_body)
        response.raise_for_status()

        os.environ["PROJECT_ID"] = project_id

    with _exec_sync_lock:
        if project_id not in _exec_states_sync:
            _exec_states_sync[project_id] = {'count': 0, 'cond': threading.Condition()}
        state = _exec_states_sync[project_id]
        state['count'] += 1

    try:
        execute_url = f"{api_url}/projects/{project_id}/execute"
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        body = {"command": command, "working_dir": working_dir}
        if script_type:
            body["script_type"] = script_type
        if interpreter:
            body["interpreter"] = interpreter
        if conda_env:
            body["conda_env"] = conda_env
        if timeout is not None:
            body["timeout"] = str(timeout)

        try:
            response = requests.post(execute_url, headers=headers, json=body)
            if response.status_code == 503:
                return "Server is busy, please try again later."
            if response.status_code == 409:
                return f"Error when running {command}, A command is already running in this project. This is because there are prior tasks that have not yet been completed."
            response.raise_for_status()
            task_id = response.json()["id"]
        except Exception as e:
            return f"Failed to submit: {str(e)}"

        if not wait:
            return task_id

        backoff_times = [60, 300, 600]
        error_count = 0

        while True:
            try:
                status_url = f"{api_url}/status/{task_id}"
                status_resp = requests.get(status_url)
                status_resp.raise_for_status()
                status = status_resp.json()
                error_count = 0
                if not status["is_running"]:
                    output_url = f"{api_url}/history/{task_id}/output"
                    output_resp = requests.get(output_url)
                    output_resp.raise_for_status()
                    output = output_resp.json()["output"]
                    returncode = status["returncode"]
                    output = truncate_output(output, max_lines=max_lines)
                    output = rm_lockfiler_libmamba(output)
                    time.sleep(1)
                    if returncode != 0:
                        if not script_type:
                            return f"Error (return code {returncode}) when running {command}: \n{output}"
                        else:
                            return f"Error (return code {returncode}) when running script: \n{output}"
                    if not output or len(output) < 3:
                        output = "<No output>"
                    if script_type:
                        output = f"Successful running script. Output:\n{output}"
                    else:
                        output = f"Successful running: {command}. \nOutput:\n{output}"

                    return output
            except Exception as e:
                if error_count >= len(backoff_times):
                    return f"Failed to get status after {error_count + 1} attempts: {str(e)}"
                time.sleep(backoff_times[error_count])
                error_count += 1

            time.sleep(1)
    finally:
        with state['cond']:
            state['count'] -= 1
            if state['count'] == 0:
                state['cond'].notify_all()
            else:
                state['cond'].wait()

def truncate_output(output, max_lines=30):
    """
    Truncates output to first and last max_lines lines if too long.
    """
    lines = output.split('\n')
    if len(lines) <= 2 * max_lines:
        return output
    truncated = '\n'.join(lines[:max_lines]) + f"\n...truncate {len(lines) - 2 * max_lines} lines ...\n\n" + '\n'.join(lines[-max_lines:])
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

def write_file_to_api(content: str, file_path: str) -> str:
    """
    Calls the write_file API to write text content to a file.
    
    :param server_url: The base URL of the API server (e.g., "http://localhost:38000")
    :param project_id: The project ID
    :param api_key: The API key for authentication
    :param file_path: The relative path to the file
    :param content: The text content to write
    :return: Response message as text
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not set")

    api_url = os.getenv("API_URL")
    if not api_url:
        raise ValueError("API_URL not set")
    else:
        server_url = api_url

    if working_dir is None:
        working_dir = os.getenv("WORK_DIR") or os.getcwd()

    if project_id is None:
        project_id = os.getenv("PROJECT_ID")
    try:
        response = requests.get(api_url)
        response.raise_for_status()
    except Exception as e:
        raise ValueError(f"API not reachable: {str(e)}")
    endpoint = f"{server_url}/projects/{project_id}/write_file"
    content_base64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "path": file_path,
        "content_base64": content_base64,
        "mode": "text"
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    response = requests.post(endpoint, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json().get("message", "Success")
    else:
        return f"Error: {response.status_code} - {response.text}"

def read_file_from_api(file_path: str) -> str:
    """
    Calls the read_file API to read text content from a file.
    
    :param server_url: The base URL of the API server (e.g., "http://localhost:38000")
    :param project_id: The project ID
    :param api_key: The API key for authentication
    :param file_path: The relative path to the file
    :return: The file content as text or error message
    """
    ### NOT IMPLEMENTED
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not set")

    api_url = api_url or os.getenv("API_URL")
    if not api_url:
        raise ValueError("API_URL not set")
    else:
        server_url = api_url

    if working_dir is None:
        working_dir = os.getenv("WORK_DIR") or os.getcwd()

    if project_id is None:
        project_id = os.getenv("PROJECT_ID")
    try:
        response = requests.get(api_url)
        response.raise_for_status()
    except Exception as e:
        raise ValueError(f"API not reachable: {str(e)}")
    endpoint = f"{server_url}/projects/{project_id}/read_file"
    payload = {
        "path": file_path,
        "mode": "text"
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    response = requests.post(endpoint, json=payload, headers=headers)
    if response.status_code == 200:
        content_base64 = response.json().get("content_base64")
        content = base64.b64decode(content_base64).decode("utf-8")
        return content
    else:
        return f"Error: {response.status_code} - {response.text}"

#execute_tool = Tool(name="execute_command", func=execute_command, description="Execute a Linux command and return the output.")
execute_tool = FunctionTool(execute_shell_command_via_api, description="execute a Linux command and return the output.")
write_file_tool = FunctionTool(write_file_to_api, description="write only text file to specificed path.")

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
_default_pubmed_prompt_str = """
You are an expert medical literature summarizer with deep experience in PubMed articles. Your goal is to produce a highly concise, accurate, and structured summary of multiple PubMed articles that have been collected and formatted as a single Markdown document.

### INPUT
The user will provide the full Markdown content containing all articles (each article typically starts with a title, followed by abstract, methods, results, conclusions, and any data references). Do not add any external knowledge — base everything strictly on the provided Markdown.

### TASK REQUIREMENTS (follow exactly, in this order)
1. **List ALL article titles** at the very beginning under the heading "**Article Titles**". Use a simple bullet list with the exact original titles (preserve capitalization and punctuation). Do not skip or reorder any article.

2. **For each article**, create a separate summary section under the heading "**Summary of [Exact Title]**".  
   Each summary MUST include:
   - Main methods (1-2 sentences only, focus on study design, key techniques, sample size if mentioned)
   - Key conclusions (1-2 sentences only, focus on primary findings and implications)
   - If the article explicitly mentions any external data, public datasets, self-generated data, or supplementary data, add a bullet line: "**Data IDs referenced:**" followed by the exact IDs, accession numbers, GEO IDs, SRA IDs, or dataset names mentioned. If no data IDs are mentioned, omit this line entirely.

3. **Length constraint**: The ENTIRE output (titles + all summaries combined) must be strictly fewer than 1000 words. Use extremely concise language, avoid repetition, and eliminate any unnecessary words. Before finalizing your response, count the words and ensure compliance.

### OUTPUT FORMAT (use exactly this structure — no extra headings, no introductions, no conclusions, no explanations)
**Article Titles**
- [Title 1]
- [Title 2]
- ...

**Summary of [Exact Title 1]**
[Main authors and journal]
[Concise paragraph covering methods + conclusions]
**Data IDs referenced:** [IDs if present]

**Summary of [Exact Title 2]**
[Main authors and journal]
[Concise paragraph covering methods + conclusions]
**Data IDs referenced:** [IDs if present]

...

### ADDITIONAL RULES
- Use neutral, scientific tone.
- Never use phrases like "the study found" or "according to the paper" — go straight to the facts.
- If the Markdown contains only one article, still follow the exact format.
- If no data IDs appear in any article, do not add empty "Data IDs referenced:" lines.
"""
def pubmed_search_to_rag_call(keyword: str, max_results: int = 30, content: bool = True, content_summary: bool = True, summary_prompt: str = _default_pubmed_prompt_str):
    _content = pubmed_search_to_rag(keyword, rag_memory_pubmed, max_results, content=content)
    if content and content_summary:
        def _get_agent(model, system_prompt):
            ## assume autogen > 0.7.5, model id autogen model class, creat a simple agents to summary markdown
            #from autogen import AssistantAgent
            #llm_config = {"config_list": [{"model": model}]}
            #agent_kwargs = {
            #        'name': 'chat message summary agent',
            #        'model_client': model,
            #        'description': 'summary long chat message history',
            #        'system_message': system_prompt,
            #    }
            agent = AssistantAgent(
                        name = 'chat_message_summary_agent',
                        model_client = model,
                        description = 'summary long chat message history',
                        system_message = system_prompt,
            )
            return agent
        logger.info(f"pubmed_search_to_rag_call: system prompt is \n{summary_prompt}")
        summary_agent = _get_agent(content_summary_model, summary_prompt)
        system_prompt = summary_prompt + '\n' + 'Now process the following Markdown content and generate the summary \n' + _content
        content_text = asyncio.run(summary_agent.run(task=system_prompt))
        content_text = content_text.messages[-1].content
    if not content:
        return 'Successfully searched PubMed and added results to internal memory.'
    if content and not content_summary:
        return 'Successfully searched PubMed and added results to internal memory.\nContent are \n' + _content
    if content and content_summary:
        return 'Successfully searched PubMed and added results to internal memory.\nContent Summary are \n' + content_text
        
pubmed_search_to_rag_tool = FunctionTool(pubmed_search_to_rag_call, description="Search PubMed for articles related to a query and add the content to the agent's memory. By default, the retrieved content will only be loaded into memory and return short LLM summary. To directly obtain the retrieved content within the session, set content to True. Since the text content may be quite long, content_summary default set to True to automatically summarize the text if need. In this case, you can set the summary_prompt to specify how the text is or set content_summary to false to get full content.")

## workflow memory
if os.environ['WORKFLOW_DATABASE'] and os.path.exists(os.environ['WORKFLOW_DATABASE']):
    nf_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="nf_cores_pipelines",
            persistence_path=os.environ['WORKFLOW_DATABASE'],
            k=15,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
                model_name="all-MiniLM-L6-v2"  # Use default model for testing all-MiniLM-L6-v2
            ),
        )
    )
else:
    nf_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="nf_cores_pipelines",
            persistence_path=os.path.join(str(Path.home()), ".all-MiniLM-embedding.chromadb_autogen.nfcore2"),
            k=15,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
                model_name="all-MiniLM-L6-v2"  # Use default model for testing all-MiniLM-L6-v2
            ),
        )
    )


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
        persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen.conda_meta1"),
        k=3,  # Return top 3 results
        score_threshold=0.4,  # Minimum similarity score
    )
)

# if CONDA_META_DATABASE set and path exists, load conda metadata to memory
if os.environ.get('CONDA_META_DATABASE') and os.path.exists(os.environ.get('CONDA_META_DATABASE')):
    asyncio.run(conda_memory.close())

    conda_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="conda_metadata",
            persistence_path=os.environ.get('CONDA_META_DATABASE'),
            k=3,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
        )
    )

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
    def _split_text(self, text: str) -> list[str]:
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

if remote_tool_loaded and os.environ.get('SKIP_REMOTE_CUSTOM_TOOL', 'false') != 'true':
    def _split_text(text: str) -> list[str]:
        """Split text into fixed-size chunks."""
        chunk_size = 8096
        chunks: list[str] = []
        # Just split text into fixed-size chunks
        for i in range(0, len(text), chunk_size):
            chunk = text[i : i + chunk_size]
            chunks.append(chunk.strip())
        return chunks
    logger.info(f"{remote_tool_description}")
    chunks = _split_text(remote_tool_description)
    print(chunks)
    total_chunks = 0
    for i, chunk in enumerate(chunks):
               doc = MemoryContent(
                   content=chunk,
                   mime_type=MemoryMimeType.TEXT,
                   metadata={"source": 'remote tools', "chunk_index": i}
               )
               asyncio.run(rag_memory_pubmed.add(doc))
               total_chunks += 1
    logger.info(f"Added {total_chunks} chunks from remote_tool_description to rag_memory_pubmed memory.")

if __name__ == "__main__":
    input_func = input
else:
    input_func = user_input_func
user_proxy = UserProxyAgent("user_proxy")


web_surfer_agent = MultimodalWebSurfer(
        "WebSurfer",
        model_client=default_model,
    )

memory_dict = {
    "user_memory": user_memory,
    "rag_memory_pubmed": rag_memory_pubmed,
    "nf_memory": nf_memory,
    "conda_memory": conda_memory,
}

tool_dict = {
    "execute_tool": execute_tool,
    "add_to_memory_func": add_to_memory_func,
    "pubmed_search_to_rag_tool": pubmed_search_to_rag_tool,
    "write_file_tool": write_file_tool,
    "list_files": FunctionTool(list_files, description="List all files in a specified directory and its subdirectories, returning the absolute path, size, and modification time of the files in JSON format."),
}

if len(custom_tools) > 0:
    logger.info(f'Load custom tools {len(custom_tools)} to tool_dict')
    tool_dict = {**tool_dict, **custom_tools}
    
logger.debug(f'{custom_tools.keys()}')

remote_description = None if not remote_tool_loaded else remote_tool_description
if use_external_agents_config:
    agents = load_agents(agent_yaml, model_clients, default_model_client=default_model_name, memory=memory_dict, tools=tool_dict, skip_params_model_content=SKIP_MODEL_CONTEXT, remote_tools=remote_description)
else:
    agents = load_agents(SYSTEM_CONFIG_PATH, model_clients, default_model_client=default_model_name, memory=memory_dict, tools=tool_dict, skip_params_model_content=SKIP_MODEL_CONTEXT, remote_tools=remote_description)
agents =[agent for agent in agents.values()]

agents_non_proxy = [agent for agent in agents if agent.name != 'user_proxy']
agents_non_proxy.append(web_surfer_agent)

if sys_config.get('builtin_agent', False):
    if __name__ == '__main__':
        agents.append(user_proxy)
    agents.append(web_surfer_agent)



# Set the termination condition
textMentionTermination = sys_config.get('textMentionTermination', 'TERMINATETERMINATE')
termination = TextMentionTermination(textMentionTermination)
external_termination = ExternalTermination()

# Create the group chat
group_chat = RoundRobinGroupChat(
    agents,
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

#tasks = """
#    You are a knowledgeable bioinformatics assistant. You run in a Linux environment. \
#    Assume workdir is {work_dir_env}, \
#    You need to understand the user's requirements about specific Bioinformatics tasks, \
#    first call @user_proxy to get user input, \
#    check the legitimacy of the requirements, and implement them through appropriate and secure Linux commands. \
#    If necessary, before fulfilling the user's requirements, you can decide to ask @system_check_agent to generate command to check the system or confirm some information (eg: software version). These commands must also undergo security checks. \
#    @bio_micromamba_env_agent could help prepare micromamba env, all new envs should store at [work_dir]/envs \
#    @file_agent could help you list file in specific path and subdir as json format, \
#    When a certain method fails, you need to try different methods and share the information with team members you will asked. \
#    If multiple attempts fail, require user's help or terminate the process. You also can search web by @web_surfer_agent,\
#    please note that you cannot assume or perform any operations as superusers. \
#    You need to be aware that you may have a limited context length. To maintain focus on the task during long conversation, update necessary memory via @manager_mem_agent.  \
#    Only one agents called each time
#""".format(work_dir_env = os.environ['WORK_DIR'])

if __name__ == '__main__':
    tasks = sys_config.get('start_prompt', '').format(work_dir_env = os.environ['WORK_DIR'])
    if remote_tool_loaded: 
        try: 
            #def set_remote_tools(tools_dict: dict, project_id: str, api_base_url: str, api_key: str, working_dir: str = None) -> dict:
            _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
        except Exception as e:
            logger.warning(f'biogen error: {e}')
        
selector_team = SelectorGroupChat(
    agents,
    model_client=default_model,
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
    user_input_func2
) -> SelectorGroupChat:
    user_proxy = UserProxyAgent('user_proxy', input_func=user_input_func2)
    agents = agents.append(user_proxy)
    selector_team = SelectorGroupChat(
    agents,
    model_client=default_model,
    termination_condition=termination,
    selector_prompt=selector_prompt,
    allow_repeated_speaker=False,  # Allow an agent to speak multiple turns in a row.
)
    return selector_team


if __name__ == "__main__":
    asyncio.run(main())
    exit(0)

#agents_non_proxy.append(user_proxy)
#selector_team2 = SelectorGroupChat(
#    agents_non_proxy,
#    model_client=default_model,
#    termination_condition=termination,
#    selector_prompt=selector_prompt,
#    allow_repeated_speaker=False,  # Allow an agent to speak multiple turns in a row.
#)