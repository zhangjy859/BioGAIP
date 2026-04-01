import sys, os
import time
import threading
import queue
import datetime
from datetime import timedelta
import json
import secrets
import subprocess
import threading
import uuid as uuid4
import collections
from typing import Deque, Tuple
from queue import Queue, Empty

import openai
from openai import RateLimitError, BadRequestError, APITimeoutError, APIConnectionError
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage, ModelClientStreamingChunkEvent, ToolCallExecutionEvent, \
    ToolCallRequestEvent, UserInputRequestedEvent, ThoughtEvent, ToolCallSummaryMessage, MultiModalMessage
from autogen_agentchat.teams._group_chat._events import GroupChatMessage

#sys.path.append('/mnt/e/software/bioGen')
#sys.path.append('/mnt/e/software/bioGen/bioGen')

import sys, os
import streamlit as st
import random
from bioGen.biogen import *
import bioGen.context_summary as bg_summary
from bioGen.web import config as web_config
import asyncio
from typing import cast
import multiprocessing
from multiprocessing import Process, Event
import signal
from streamlit_cookies_manager import EncryptedCookieManager
#from streamlit_js_eval import streamlit_js_eval

import logging
from autogen_core.logging import LLMCallEvent
from autogen_core import EVENT_LOGGER_NAME

import pypdf  # Added for PDF text extraction

class LLMUsageTracker(logging.Handler):
    def __init__(self) -> None:
        """Logging handler that tracks the number of tokens used in the prompt and completion."""
        super().__init__()
        self._prompt_tokens = 0
        self._completion_tokens = 0

    @property
    def tokens(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    @property
    def prompt_tokens(self) -> int:
        return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self._completion_tokens

    def reset(self) -> None:
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Emit the log record. To be used by the logging module."""
        try:
            # Use the StructuredMessage if the message is an instance of it
            if isinstance(record.msg, LLMCallEvent):
                event = record.msg
                self._prompt_tokens += event.prompt_tokens
                self._completion_tokens += event.completion_tokens
        except Exception:
            self.handleError(record)

def restart_session():
    os.execv(sys.executable, [sys.executable] + sys.argv)

# Set up the logging configuration to use the custom handler
logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.setLevel(logging.INFO)
llm_usage = LLMUsageTracker()
logger.handlers = [llm_usage]

version_data = 'v1.3.1'


# Define starters similar to Chainlit's set_starters
# from web config
starters = web_config.starters

max_chat_message_num = os.environ.get('MAX_CHAT_MESSAGE', 200)


def create_user_input_func(input_file, log_file):
    def user_input_func(prompt: str) -> str:
        with open(log_file, 'a') as f:
            json.dump({'type': 'prompt', 'prompt_type': 'input', 'content': prompt}, f)
            f.write('\n')
        while True:
            try:
                with open(input_file, 'r') as f:
                    response = f.read().strip()
                if response:
                    with open(input_file, 'w') as f:
                        pass
                    return response
            except:
                pass
            time.sleep(0.5)
    return user_input_func


def create_user_action_func(input_file, log_file):
    def user_action_func(prompt: str) -> str:
        with open(log_file, 'a') as f:
            json.dump({'type': 'prompt', 'prompt_type': 'action', 'content': prompt}, f)
            f.write('\n')
        while True:
            with open(input_file, 'r') as f:
                response = f.read().strip()
            if response:
                with open(input_file, 'w') as f:
                    pass
                return response
            time.sleep(0.5)
    return user_action_func


def shutdown_server(host=None, api_key=None):
    if not api_key or not host:
        raise ValueError("API key is required")
    response = requests.post(f"{host}/shutdown", headers={"x-api-key": api_key})
    response.raise_for_status()  # 如果响应状态码不是200，会抛出异常
    return response.json()

# Tasks string
tasks = """You are a knowledgeable bioinformatics assistant. You run in a Linux environment.
Assume workdir is {work_dir_env},
You need to understand the user's requirements about specific Bioinformatics tasks,
first call @user_proxy to get user input,
check the legitimacy of the requirements, and implement them through appropriate and secure Linux commands.
If necessary, before fulfilling the user's requirements, you can decide to ask @system_check_agent to generate command to check the system or confirm some information (eg: software version). These commands must also undergo security checks.
@bio_micromamba_env_agent could help prepare micromamba env, all new envs should store at [work_dir]/envs
@file_agent could help you list file in specific path and subdir as json format,
When a certain method fails, you need to try different methods and share the information with team members you will asked.
If multiple attempts fail, require user's help or terminate the process. You also can search web by @web_surfer_agent,
please note that you cannot assume or perform any operations as superusers.
You need to be aware that you may have a limited context length. To maintain focus on the task during long conversation, update necessary memory via @manager_mem_agent.
Only one agent called each time
""".format(work_dir_env=os.environ.get('WORK_DIR', ''))

if 'start_prompt' in sys_config:
    tasks = sys_config.get('start_prompt', '').format(work_dir_env = os.environ['WORK_DIR'])

# Define agent avatars
agent_avatars = {
    "user": "🧑",
    "user_proxy": "👤",
    "system_check_agent": "🔍",
    "bio_micromamba_env_agent": "🧪",
    "file_agent": "📁",
    "web_surfer_agent": "🌐",
    "manager_mem_agent": "🧠",
    "system": "⚙️",
    "planning_agent": "🗂️",
    "query_agent": "❓",
    "command_generator_agent": "💻",
    "code_generator_agent": "📝",
    "safety_checker_agent": "🛡️",
    "executor_agent": "🚀",
    "assistant": "🤖",
}


def get_avatar(name):
    return agent_avatars.get(name, "🤖")


work_dir_env = os.getcwd()
persist_dir_env = os.environ.get('PERSIST_DIR', None)
if persist_dir_env is None:
    # add reandom string to avoid conflict
    persist_dir = os.path.join(work_dir_env, 'user_sessions') + f"_{random.randbytes(3).hex()}"
    os.environ['PERSIST_DIR'] = persist_dir
    #logger.info(f'PERSIST_DIR seted to {persist_dir}, persist_dir_env is {persist_dir_env}')
else:
    persist_dir = persist_dir_env
    #logger.info(f'PERSIST_DIR seted to {persist_dir}, persist_dir_env is {persist_dir_env}')
os.makedirs(persist_dir, exist_ok=True)

cookiers_password = os.environ.get("COOKIE_PASSWORD", None)
if not cookiers_password and not st.session_state.get('cookier_password', None):
    # ramdo,
    cookiers_password = random.randbytes(64).hex()
    os.environ["COOKIE_PASSWORD"] = cookiers_password
if not st.session_state.get('cookier_password', None):
    st.session_state.cookier_password = os.environ["COOKIE_PASSWORD"]

cookies = EncryptedCookieManager(
    prefix="biogen_",
    password=st.session_state.cookier_password
    # Set a secure password, preferably from env
)

if not cookies.ready():
    st.stop()

# Simple password auth
if "authenticated" not in st.session_state:
    if 'authenticated' in cookies and cookies['authenticated'] == 'True':
        try:
            st.session_state.authenticated = True
            st.session_state.login_time = datetime.datetime.fromisoformat(cookies['login_time'])
            st.session_state.username = cookies['username']
        except ValueError:
            # Invalid login_time format, clear cookies
            del cookies['authenticated']
            if 'login_time' in cookies:
                del cookies['login_time']
            if 'username' in cookies:
                del cookies['username']
            cookies.save()
            st.session_state.authenticated = False
        except KeyError:
            # Missing keys, clear cookies
            del cookies['authenticated']
            if 'login_time' in cookies:
                del cookies['login_time']
            if 'username' in cookies:
                del cookies['username']
            cookies.save()
            st.session_state.authenticated = False
    else:
        st.session_state.authenticated = False


def load_session():
    session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
    #if 'stop_team' in st.session_state and st.session_state.stop_team.is_set() and os.path.exists(session_file): 
    #    os.remove(session_file)
    if os.path.exists(session_file):
        with open(session_file, 'r') as f:
            data = json.load(f)
            st.session_state.messages = data.get('messages', [])
            st.session_state.prompt_history = data.get('prompt_history', "")
            if 'project_id' in data:
                st.session_state.project_id = data['project_id']
            st.session_state.processing = data.get('processing', False)
            if 'pending_prompt' in data:
                st.session_state.pending_prompt = data['pending_prompt']
            if 'pending_prompt_type' in data:
                st.session_state.pending_prompt_type = data['pending_prompt_type']
            if 'input_prompt' in data:
                st.session_state.input_prompt = data['input_prompt']
        logger.info(f'loaded session from {session_file}')
    if not st.session_state.get('reload_session', False):
        st.session_state.reload_session = True

def save_agents(team, file):
    agent_state = asyncio.run(team.save_state())
    logger.info(f'{agent_state}')
    def _convert_datetimes(data):
        """
        Recursively converts all datetime objects in a nested dict (or list) to ISO format strings,
        while preserving the original structure.
        """
        if isinstance(data, dict):
            return {k: _convert_datetimes(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [_convert_datetimes(item) for item in data]
        elif isinstance(data, datetime.datetime):
            return data.isoformat()
        else:
            return data
    agent_state = _convert_datetimes(agent_state)
    with open(file, "w") as f:
        json.dump(agent_state, f)
    return file
    
    

def save_session():
    if st.session_state.get('messages', "") == "":
        logger.warning('save empty session, not allowed')
        return
    if 'username' in st.session_state:
        session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
        logger.info(f'Save session file to {session_file}')
        data = {
            'messages': st.session_state.get('messages', []),
            'prompt_history': st.session_state.get('prompt_history', ""),
            'project_id': st.session_state.get('project_id', None),
            'processing': st.session_state.get('processing', False),
            'pending_prompt': st.session_state.get('pending_prompt', None),
            'pending_prompt_type': st.session_state.get('pending_prompt_type', None),
            'input_prompt': st.session_state.get('input_prompt', False)
        }
        with open(session_file, 'w') as f:
            json.dump(data, f)


## st.title
st.set_page_config(page_title=f"BioGAIP, a generative AI platform for bioinfomatics analysis {version_data}", page_icon=":smile:")
#st.title(f"BioGAIP, a generative AI platform for bioinfomatics analysis {version_data}")

if not st.session_state.authenticated:
    # Display logo on login page
    logo_url = "https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505"  # Replace with your specified logo URL
    #left_co, cent_co, last_co = st.columns(3)
    ## add some space
    st.markdown(
        '''
        <div style="text-align: center;">
            <img src="{logo_url}" alt="Example Image" style="max-width: 25%; height: auto;">
        </div>
        '''.format(logo_url=logo_url), unsafe_allow_html=True
    )
    st.markdown('####')
    col1, col2, col3 = st.columns(3)
    #with cent_co:
    #    st.image(logo_url, width=300)
    with col2:
        #st.image(logo_url, width=150)  # Set width to make it slightly smaller
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        with st.expander("Advanced Settings"):
            usrname_id_login = st.text_input("Project ID (optional)", value="")
        if st.button("Login"):
            app_user = os.environ.get('APP_USER')
            if app_user:
                parts = app_user.split(':', 1)
                expected_username = parts[0]
                expected_password = parts[1] if len(parts) > 1 else ''
            else:
                expected_username = "admin"
                expected_password = "admin"
            if username == expected_username and password == expected_password:
                st.session_state.authenticated = True
                st.session_state.login_time = datetime.datetime.now()
                st.session_state.username = username
                cookies['authenticated'] = 'True'
                cookies['login_time'] = st.session_state.login_time.isoformat()
                cookies['username'] = username
                if usrname_id_login:
                    st.session_state.project_id = usrname_id_login
                    project_id = usrname_id_login
                    cookies['project_id'] = project_id
                cookies.save()
                load_session()
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()
else:
    # Check if session has expired
    if (datetime.datetime.now() - st.session_state.login_time) > timedelta(days=3):
        st.session_state.authenticated = False
        if 'authenticated' in cookies:
            del cookies['authenticated']
        if 'login_time' in cookies:
            del cookies['login_time']
        if 'username' in cookies:
            del cookies['username']
        if 'project_id' in cookies:
            del cookies['project_id']
        cookies.save()
        st.rerun()
    else:
        # Load session if not already loaded
        if 'session_loaded' not in st.session_state:
            load_session()
            st.session_state.session_loaded = True
            # Check for reconnection during processing and show warning if needed
            if st.session_state.get('processing', False) and 'reconnect_warning_shown' not in st.session_state:
                st.warning(
                    "You seem to have reconnected while a task was processing. Some recent chat records might have been lost. "
                    "To avoid this in the future, please keep your browser tab open and active, disable tab sleep in your browser settings, "
                    "and avoid refreshing the page during long tasks."
                )
                st.session_state.reconnect_warning_shown = True
                save_session()

# Display project logo in sidebar
st.sidebar.image(
    "https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505")

# Add logout and reset buttons in sidebar
st.sidebar.title("Options")
if st.sidebar.button("Logout"):
    if 'authenticated' in cookies:
        del cookies['authenticated']
    if 'login_time' in cookies:
        del cookies['login_time']
    if 'username' in cookies:
        del cookies['username']
    if 'project_id' in cookies:
        del cookies['project_id']
    cookies.save()
    st.session_state.clear()
    if 'api_process' in st.session_state:
        st.session_state.api_process.kill()
        del st.session_state.api_process
    st.info('Please Manual Refresh web page')

pid_file = os.path.join(persist_dir, f"{st.session_state.username}.process_pid")

@st.dialog("Reset Session Warning")
def reset_session_confirm():
    st.warning("This will terminate any running tasks and start a new session. All current progress will be lost. Are you sure?")
    if st.button("Confirm Reset"):
        st.info("Reseting session")
        if 'stop_team' in st.session_state: 
            try:
                st.session_state.stop_team.set()
            except (AttributeError) as e:
                st.session_state.team_exit_file_set = team_exit_file + '_set'
                with open(st.session_state.team_exit_file_set, 'w') as f:
                    f.write('')
        if 'force_stop' in st.session_state:
            st.session_state.force_stop.set()
        # 1. Abort current team run
        #logger.info('Reset session')
        st.session_state.messages.append({"role": "user", "content": 'user stop session'})
        
        waiting_team_stop = True
        while not os.path.exists(st.session_state.team_exit_file) and waiting_team_stop:
            logger.info('Stop team but team is still running, waiting')
            st.toast("Waitting team stop", icon="ℹ️")
            time.sleep(30)
            waiting_team_stop = False
        if not os.path.exists(st.session_state.team_exit_file):
            logger.info('Stop team fail because team is still running after wait 30s')
            st.toast("Stop team fail, team is still running after wait 30s, force stoping...", icon="ℹ️")
            force_kill_process(pid_file)
            #project_status = None
            #st.rerun()
            waiting_team_stop = False
        else:
            logger.info('Stop team ok')
            os.remove(st.session_state.team_exit_file)      
        if 'team' in st.session_state:
            del st.session_state.team
        st.session_state.processing = False
        st.session_state.show_refresh_botton = True
        
        # 2. Terminate current project task if running
        if 'project_id' in st.session_state:
            st.info("Reseting project")
            #logger.info(f"Reset_session_confirm: Reset project id")
            project_status = get_project_status(st.session_state.project_id, API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
            if isinstance(project_status, dict) and project_status.get('status') == 'running':
                task_id = project_status.get('current_task_id')
                if task_id:
                    try:
                        response = requests.post(
                            f"{os.environ.get('API_URL')}/tasks/{task_id}/kill",
                            headers={"x-api-key": os.environ.get('API_KEY')}
                        )
                        response.raise_for_status()
                    except Exception as e:
                        st.error(f"Failed to kill task: {str(e)}")
        
        # 3. Initialize new session and new project id
        st.session_state.messages = []
        st.session_state.prompt_history = ""
        session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
        if os.path.exists(session_file):
            os.remove(session_file)

        # Get new project_id
        asyncio.run(execute_shell_command_via_api(command=''))
        st.session_state.project_id = os.environ["PROJECT_ID"]
        if remote_tool_loaded: 
            try: 
                #def set_remote_tools(tools_dict: dict, project_id: str, api_base_url: str, api_key: str, working_dir: str = None) -> dict:
                _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
                logger.info(f"set_remote_tools: {_}")
            except Exception as e:
                logger.warning(f'biogen error: {e}')
        # Update log_file and input_file
        st.session_state.log_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_log.ndjson")
        st.session_state.input_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_input.txt")
        if not os.path.exists(st.session_state.log_file):
            open(st.session_state.log_file, 'w').close()
        if not os.path.exists(st.session_state.input_file):
            open(st.session_state.input_file, 'w').close()
        # Reset input status
        if 'pending_prompt' in st.session_state:
            del st.session_state.pending_prompt
        if 'pending_prompt_type' in st.session_state:
            del st.session_state.pending_prompt_type
        if 'input_prompt' in st.session_state:
            del st.session_state.input_prompt
        st.session_state.processing = False
        save_session()
        st.session_state.authenticated = False
        if 'authenticated' in cookies:
            del cookies['authenticated']
        if 'login_time' in cookies:
            del cookies['login_time']
        if 'username' in cookies:
            del cookies['username']
        if 'project_id' in cookies:
            del cookies['project_id']
        cookies.save()
        st.session_state.clear()
        if 'api_process' in st.session_state:
            st.session_state.api_process.kill()
            del st.session_state.api_process
        st.info('Please Manual Refresh web page')
        _ = restart_session()
        st.rerun()

if st.sidebar.button("Reset Session"):
    #logger.info('Reset session')
    reset_session_confirm()
    st.components.v1.html(
        """
        <script>
        window.location.reload(true);
        </script>
        """,
        height=0, 
        width=0,
    )


# Check for API_URL and API_KEY
def check_api(reset_project_id=False):
    ## print work dir
    print('work dir:', os.environ.get('WORK_DIR', ''))
    print('api url:', os.environ.get('API_URL', ''))
    #print('api key:', os.environ.get('API_KEY', ''))
    try:
        # Assuming execute_shell_command_via_api uses API_URL and API_KEY
        # result = asyncio.run(execute_shell_command_via_api(command=''))
        if ('project_id' not in st.session_state and os.getenv('PROJECT_ID') is None) or reset_project_id:
            result = asyncio.run(execute_shell_command_via_api(command=''))
            st.session_state['project_id'] = os.environ["PROJECT_ID"]
            print('after check api', st.session_state['project_id'])
            if remote_tool_loaded: 
                try: 
                #def set_remote_tools(tools_dict: dict, project_id: str, api_base_url: str, api_key: str, working_dir: str = None) -> dict:
                    _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
                    logger.info(f"set_remote_tools: {_}")
                except Exception as e:
                    logger.info(f'biogen error: {e}')
        else:
            result = asyncio.run(execute_shell_command_via_api(command='echo ok'))
        if result:
            return True
        else:
            return False
    except Exception as e:
        st.error(f"API check failed: {str(e)}")
        raise e
    return False


def api_set2(server_ip, username, port, ssh_password, api_key, read_only_dir='', read_write_dir='', work_dir='', allow_raw=''):
    cmd = ['bash', './bioGen/ulits/api_call_debug.sh', server_ip, username, port, ssh_password, api_key, read_only_dir, read_write_dir, work_dir, str(allow_raw)]
    print("Running command:", ' '.join(cmd))
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                               universal_newlines=True)
    output = ""
    while True:
        line = process.stdout.readline()
        if line:
            output += line
            print(line)
            if "Successfully started bioGen API server" in line:
                os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                os.environ['API_KEY'] = api_key
                st.session_state.api_process = process  # Keep the process reference to prevent it from being garbage collected
                st.info(f"API setup completed. View progression at {os.environ.get('API_URL')} with your API key")
                return True
        err_line = process.stderr.readline()
        if err_line:
            print(err_line)
            st.error(f"Error outout: {err_line}")
        #    process.kill()
        #    return False
        if process.poll() is not None:
            # Process exited without success
            return False

    return False


import re
if os.name != "nt":
    import pty
    import fcntl
import select

    

def api_set(server_ip, username, port, ssh_password, api_key, read_only_dir='', read_write_dir='', work_dir='', allow_raw='', use_sandbox_type=None):
    cmd = ['bash', './bioGen/ulits/api_set_warp.sh', server_ip, username, port, ssh_password, api_key, read_only_dir, read_write_dir, work_dir, str(allow_raw)]
    
    if use_sandbox_type:
        cmd.append(['--use_sandbox', use_sandbox_type])
    
    #print("Running command:", ' '.join(cmd))

    stdout_master, stdout_slave = pty.openpty()
    stderr_master, stderr_slave = pty.openpty()

    process = subprocess.Popen(cmd, stdout=stdout_slave, stderr=stderr_slave, close_fds=True)

    os.close(stdout_slave)
    os.close(stderr_slave)

    # Set non-blocking
    for fd in (stdout_master, stderr_master):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    output = ""
    err_output = ""
    stdout_queue = Queue()
    stderr_queue = Queue()

    def read_fd(fd, queue):
        buffer = ''
        while True:
            try:
                data = os.read(fd, 4096).decode('utf-8', errors='replace')
            except OSError as e:
                if e.errno != 11:  # EAGAIN
                    break
                data = ''
            if not data:
                if process.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                queue.put(line + '\n')
        if buffer:
            queue.put(buffer)

    threading.Thread(target=read_fd, args=(stdout_master, stdout_queue), daemon=True).start()
    threading.Thread(target=read_fd, args=(stderr_master, stderr_queue), daemon=True).start()

    success = False
    progress_bar = st.progress(0, text="Starting API setup...")

    while True:
        # Process all available stdout lines
        try:
            while True:
                line = stdout_queue.get_nowait()
                if line:
                    output += line
                    print(line, end='')
                    match = re.match(r'^%(\d+)%\s*(.*)$', line.strip())
                    if match:
                        print('progress match:', match.group(1), match.group(2))
                        percent = int(match.group(1))
                        message = match.group(2)
                        progress_bar.progress(percent / 100.0, text=message)
                        time.sleep(0.1)  # Allow Streamlit UI to refresh
                    if "Successfully started bioGen API server" in line:
                        os.environ['API_URL'] = f"http://{server_ip}:{port}"
                        os.environ['API_KEY'] = api_key
                        st.session_state.api_process = process
                        st.info(f"API setup completed. View progression at {os.environ.get('API_URL')} with your API key")
                        success = True
        except Empty:
            pass

        # Process all available stderr lines
        try:
            while True:
                err_line = stderr_queue.get_nowait()
                if err_line:
                    err_output += err_line
                    print(err_line, end='')
                    st.error(f"Error output: {err_line.rstrip()}")
        except Empty:
            pass

        if success:
            progress_bar.progress(1.0, text="API setup completed")
            time.sleep(0.1)  # Allow UI refresh
            # Drain any remaining lines after success
            try:
                while True:
                    line = stdout_queue.get_nowait()
                    if line:
                        output += line
                        print(line, end='')
            except Empty:
                pass

            try:
                while True:
                    err_line = stderr_queue.get_nowait()
                    if err_line:
                        err_output += err_line
                        print(err_line, end='')
                        st.error(f"Error output: {err_line.rstrip()}")
            except Empty:
                pass
            os.close(stdout_master)
            os.close(stderr_master)
            return success, output, err_output

        if process.poll() is not None:
            if not success:
                # Drain any remaining lines after process exit
                try:
                    while True:
                        line = stdout_queue.get_nowait()
                        if line:
                            output += line
                            print(line, end='')
                except Empty:
                    pass

                try:
                    while True:
                        err_line = stderr_queue.get_nowait()
                        if err_line:
                            err_output += err_line
                            print(err_line, end='')
                            st.error(f"Error output: {err_line.rstrip()}")
                except Empty:
                    pass

                progress_bar.progress(0, text="API setup failed")
                os.close(stdout_master)
                os.close(stderr_master)
                return False, output, err_output

        time.sleep(0.01)  # Smaller sleep for more responsive loop

    return False, "", ""  # Fallback, though unreachable

def api_set2(server_ip, username, port, ssh_password, api_key, read_only_dir='', read_write_dir='', work_dir='', allow_raw='', bioworker_port=None, use_sandbox_type=None):

    script_dir = os.path.dirname(os.path.abspath(__file__))

    if os.environ.get('BIOGEN_BYPASSMODE', '').lower() == 'true':
        script_path = os.path.join(script_dir, 'bioag', 'bioGen', 'ulits', 'api_set_sandbox.py')
        cmd_prefix = [sys.executable]
    else:
        if sys.platform.startswith('win'):
            script_path = os.path.join('.', 'bioGen', 'ulits', 'api_set_sandbox.py')
            cmd_prefix = [sys.executable]
        else:
            script_path = os.path.join('.', 'bioGen', 'ulits', 'api_set_warp.sh')
            cmd_prefix = ['bash']

    cmd = cmd_prefix + [script_path, server_ip, username, port, ssh_password, api_key, read_only_dir, read_write_dir, work_dir, str(allow_raw)]

    if use_sandbox_type:
        cmd += ['--use_sandbox', use_sandbox_type]
    if bioworker_port:
        cmd += [str(bioworker_port)]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)

    output = ""
    err_output = ""
    stdout_queue = Queue()
    stderr_queue = Queue()

    def read_stdout(queue):
        for line in iter(process.stdout.readline, b''):
            queue.put(line.decode('utf-8', errors='replace'))
        queue.put(None)  # Signal end

    def read_stderr(queue):
        for line in iter(process.stderr.readline, b''):
            queue.put(line.decode('utf-8', errors='replace'))
        queue.put(None)  # Signal end

    threading.Thread(target=read_stdout, args=(stdout_queue,), daemon=True).start()
    threading.Thread(target=read_stderr, args=(stderr_queue,), daemon=True).start()

    success = False
    progress_bar = st.progress(0, text="Starting API setup...")

    while True:
        # Process all available stdout lines
        try:
            while True:
                line = stdout_queue.get_nowait()
                if line is None:
                    break
                if line:
                    output += line
                    print(line, end='')
                    match = re.match(r'^%(\d+)%\s*(.*)$', line.strip())
                    if match:
                        print('progress match:', match.group(1), match.group(2))
                        percent = int(match.group(1))
                        message = match.group(2)
                        progress_bar.progress(percent / 100.0, text=message)
                        time.sleep(0.1)  # Allow Streamlit UI to refresh
                    if "Successfully started bioGen API server" in line:
                        os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                        os.environ['API_KEY'] = api_key
                        st.session_state.api_process = process
                        st.info(f"API setup completed. View progression at {os.environ.get('API_URL')} with your API key")
                        success = True
        except Empty:
            pass

        # Process all available stderr lines
        try:
            while True:
                err_line = stderr_queue.get_nowait()
                if err_line is None:
                    break
                if err_line:
                    err_output += err_line
                    print(err_line, end='')
                    st.error(f"Error output: {err_line.rstrip()}")
        except Empty:
            pass

        if success:
            progress_bar.progress(1.0, text="API setup completed")
            time.sleep(0.1)  # Allow UI refresh
            # Drain any remaining lines after success
            try:
                while True:
                    line = stdout_queue.get_nowait()
                    if line is None:
                        break
                    if line:
                        output += line
                        print(line, end='')
            except Empty:
                pass

            try:
                while True:
                    err_line = stderr_queue.get_nowait()
                    if err_line is None:
                        break
                    if err_line:
                        err_output += err_line
                        print(err_line, end='')
                        st.error(f"Error output: {err_line.rstrip()}")
            except Empty:
                pass
            return success, output, err_output

        if process.poll() is not None:
            if not success:
                # Drain any remaining lines after process exit
                try:
                    while True:
                        line = stdout_queue.get_nowait()
                        if line is None:
                            break
                        if line:
                            output += line
                            print(line, end='')
                except Empty:
                    pass

                try:
                    while True:
                        err_line = stderr_queue.get_nowait()
                        if err_line is None:
                            break
                        if err_line:
                            err_output += err_line
                            print(err_line, end='')
                            st.error(f"Error output: {err_line.rstrip()}")
                except Empty:
                    pass

                progress_bar.progress(0, text="API setup failed")
                return False, output, err_output

        time.sleep(0.01)  # Smaller sleep for more responsive loop

    return False, "", ""  # Fallback, though unreachable

@st.dialog("Embedding Model Check")
def check_model():
    model_dir = os.path.expanduser("~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/")
    tar_file_path = os.path.join(model_dir, "onnx.tar.gz")
    url = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"

    if os.path.exists(model_dir) and os.path.exists(tar_file_path):
        #st.success("The model file already exists.")
        # close the dialog
        return True

    st.markdown("The Embedding model file (required by RAG) is missing. It needs to be downloaded and extracted.")

    if st.button("Download and Extract"):
        try:
            # Create directory if it doesn't exist
            os.makedirs(model_dir, exist_ok=True)

            # Download with progress
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            block_size = 1024
            progress_bar = st.progress(0)
            downloaded = 0

            with open(tar_file_path, "wb") as f:
                for data in response.iter_content(block_size):
                    downloaded += len(data)
                    f.write(data)
                    if total_size > 0:
                        progress_bar.progress(downloaded / total_size)

            st.success("Download complete!")

            # Extract
            import tarfile
            with tarfile.open(tar_file_path) as tar:
                tar.extractall(path=model_dir)

            st.success("Extraction complete!")
            # Optionally remove the tar file after extraction
            # os.remove(tar_file_path)

        except Exception as e:
            st.markdown(f"An error occurred: {str(e)}")
            return False

    return True

def pair_api_set(pair_code):
    pass  # Leave empty as per instructions


def get_project_status(project_id, API_URL=None, API_KEY=None):
    if not project_id:
        return "No Project ID"
    try:
        response = requests.get(f"{API_URL}/status/project/{project_id}",
                                headers={"x-api-key": API_KEY})
        if response.status_code == 200:
            data = response.json()
            ## to dict
            if isinstance(data, str):
                data = json.loads(data)
            return data
        else:
            return f"Error: {response.status_code}"
    except Exception as e:
        return f"Exception: {str(e)}"

if "api_setup_done" not in st.session_state:
    api_url = os.environ.get('API_URL')
    api_key = os.environ.get('API_KEY')
    if not api_url or not api_key:
        st.session_state.api_setup_done = False
    else:
        if check_api():
            st.session_state.api_setup_done = True
        else:
            st.session_state.api_setup_done = False
else:
    if st.session_state.api_setup_done:
        pass
    else:
        api_url = os.environ.get('API_URL')
        api_key = os.environ.get('API_KEY')

# API Setup Wizard
if not st.session_state.get('api_setup_done', False):
    st.header("BioWorker API Setup Wizard")
    st.info("Improper configuration may enable the AI to damage your data or device. Always back up your data and read bioGen's documentation before start.")
    tab1, tab2, tab3 = st.tabs(["Manual Setup", "SSH Setup", "Pair Code Setup"])

    with tab1:
        api_url_input = st.text_input("Enter bioWorker API URL", value=os.environ.get('API_URL', ''))
        api_key_input = st.text_input("Enter bioWorker API Key", value=os.environ.get('API_KEY', ''), type="password")
        with st.expander("Advanced Settings"):
            usrname_id_login = st.text_input("Project ID (optional)", value=st.session_state.get('project_id', ""))
        if st.button("Set API Credentials"):
            if api_url_input and api_key_input:
                os.environ['API_URL'] = api_url_input
                os.environ['API_KEY'] = api_key_input
                #reset_project_id = not (usrname_id_login != '' and usrname_id_login != st.session_state.get('project_id', ''))
                reset_project_id = usrname_id_login != ''
                if reset_project_id: 
                    st.session_state.project_id = usrname_id_login
                    project_id = usrname_id_login
                    os.environ['PROJECT_ID'] = st.session_state.project_id
                if check_api(reset_project_id=reset_project_id):
                    st.success("API credentials set successfully!")
                    st.session_state.api_setup_done = True
                    #check_model()
                    #if check_model():
                    #    st.success("Model check successful!")
                    #    st.rerun()
                    #else:
                    #    pass
                    if usrname_id_login != '' and usrname_id_login != st.session_state.get('project_id', ''):
                        st.session_state.project_id = usrname_id_login
                        project_id = usrname_id_login
                    st.rerun()
                else:
                    st.error("Invalid API credentials. Please try again.")
            else:
                st.error("Please provide both API URL and API Key.")

    with tab2:
        st.warning("This is an experimental feature and may be unstable and unsafe.")
        server_ip = st.text_input("Server IP")
        username = st.text_input("User Name")
        port = st.text_input("Port", value="22")
        ssh_password = st.text_input("SSH Password", type="password")
        st.info("Follow path is absolute path on the **remote** server side.")
        read_directory = st.text_input("Directory allowed to read, eg: /path/to/dir1;/path/to/dir2")
        read_write_directory = st.text_input("Directory allowed to read and write, eg: /path/to/dir3;/path/to/dir4")
        work_dir = st.text_input("Working Directory (Optional), bioWorker will store envs and temp files here")
        if "ssh_api_key" not in st.session_state:
            st.session_state.ssh_api_key = ""
        st.info('Please note down the generated API key, as it will not be shown again. You will need it to access the API at other place.')
        api_key = st.text_input("bioWorker API Key", value=st.session_state.ssh_api_key, type="password")
        if st.button("Generate API Key"):
            st.session_state.ssh_api_key = secrets.token_hex(64)
            st.rerun()
        with st.expander("Advanced Settings"):
            use_sandbox = st.selectbox('Sandbox Mode', ['Disabled', 'bubblewrap', 'landlock'], index=0)
            # experimental mode warning
            st.info("Sandboxing allowed restricts bioWorker's access to the system, enhancing security with docker or other containerization technology. However, it may cause issues and unsafe on some systems.")
            bioworker_port = st.text_input("Bioworker Port", value="38000")
        if use_sandbox == 'bubblewrap':
            use_sandbox_type = 'bubblewrap'
        elif use_sandbox == 'landlock':
            use_sandbox_type = 'landlock'
        elif use_sandbox == 'Disabled':
            use_sandbox_type = None
        else:
            raise ValueError("Invalid sandbox mode selected.")
        print('rw dir:', read_write_directory)
        if not read_directory:
            read_directory = ''
        if not read_write_directory:
            read_write_directory = ''
        if not work_dir:
            work_dir = ''
        if st.button("Initialize via SSH"):
            #sys.stderr.write('Initializing via SSH...')
            if server_ip and username and port and ssh_password and api_key:
                print('rw dir:', read_write_directory)
                success, output, error_output = api_set2(server_ip, username, port, ssh_password, api_key, read_directory, read_write_directory, work_dir, bioworker_port = bioworker_port, use_sandbox_type = use_sandbox_type)
                print('API set result:', success)
                if not success:
                    st.error("Setup failed. Please check the error messages.")
                    if error_output:
                        st.text_area("Error Output", error_output, height=200)
                    if output:
                        st.text_area("Output", output, height=200)
                    if 'api_process' in st.session_state:
                        st.session_state.api_process.kill()
                        del st.session_state.api_process
                    st.stop()
                os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                os.environ['API_KEY'] = api_key
                #print(os.environ['API_URL'], os.environ['API_KEY'])
                if success:
                    if check_api():
                        st.success("API setup successful!")
                        st.session_state.api_setup_done = True
                        check_model()
                        st.rerun()
                    else:
                        st.error("API check failed.")
                        if 'api_process' in st.session_state:
                            st.session_state.api_process.kill()
                            del st.session_state.api_process
                else:
                    st.error("Setup failed.")
            else:
                st.error("Please fill all fields.")

    with tab3:
        st.warning("This is an experimental feature and may be unstable and unsafe.")
        st.warning("The options in this tab are for professional users only. Please read our documentation carefully.")
        # not implemented error
        st.error("This mode is not open for user current now because of safety concerns.")
        pair_code = st.text_input("Pair Code")
        if st.button("Initialize via Pair Code"):
            pair_api_set(pair_code)
            if check_api():
                st.success("API setup successful!")
                st.session_state.api_setup_done = True
                st.rerun()
            else:
                st.error("Setup failed.")
    st.stop()

# Function to create or recreate the team
def create_team(file = None, team_summary = False, add_user_prompt = None):
    team_state = None
    if file and os.path.exists(file): 
        try: 
            with open(file, "r") as f:
                team_state = json.load(f)
        except Exception as e:
            logger.error(f'Load exist team status {file} error: {e}')
    user_input = create_user_input_func(st.session_state.input_file, st.session_state.log_file)
    user_action = create_user_action_func(st.session_state.input_file, st.session_state.log_file)
    user_proxy = UserProxyAgent('user_proxy', input_func=user_input)
    if add_user_prompt:
        pass
        # not implemented

    agents_non_proxy = [agent for agent in agents if agent.name != 'user_proxy']
    agents_non_proxy.append(user_proxy)
    selector_team2 = SelectorGroupChat(
        agents_non_proxy,
        model_client=default_model,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=False,
    )
    if team_state and not team_summary: 
        try: 
            asyncio.run(selector_team2.load_state(team_state))
            logger.error(f'Load exist team status {file} ok')
            st.session_state.init_processing = True
            logger.error(f'reset st.session_state.processing status')
        except Exception as e:
            logger.error(f'Load exist team status {file} ok, but error in recovery team status: {e}')
    else:
        ## remove session file
        if os.path.exists(st.session_state.input_file):
            os.remove(st.session_state.input_file)
        logger.info('Create new team')
    return selector_team2

# Setup on "chat start" - run once
if "setup_done" not in st.session_state:
    st.session_state.setup_done = True
    if 'input_counter' not in st.session_state:
        st.session_state.input_counter = 0  # Initialize input counter
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'project_id' not in st.session_state:
        project_id = asyncio.run(execute_shell_command_via_api(command=''))
        os.environ['PROJECT_ID'] =  project_id
        st.session_state.project_id = project_id
        if remote_tool_loaded: 
            try: 
                _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
                logger.info(f"set_remote_tools: {_}")
            except Exception as e:
                logger.info(f'biogen error: {e}')
    st.session_state.log_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_log.ndjson")
    st.session_state.input_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_input.txt")
    if not os.path.exists(st.session_state.log_file):
        open(st.session_state.log_file, 'w').close()
    if not os.path.exists(st.session_state.input_file):
        open(st.session_state.input_file, 'w').close()
    agent_status_file = os.path.join(persist_dir, f"{st.session_state.username}.agjson")
    st.session_state.agent_status_file = agent_status_file
    #st.session_state.team = create_team(file = st.session_state.agent_status_file)
    st.session_state.prompt_history = st.session_state.get('prompt_history', "")

if 'project_id' not in st.session_state:
    project_id = asyncio.run(execute_shell_command_via_api(command=''))
    os.environ['PROJECT_ID'] =  project_id
    st.session_state.project_id = project_id
    if remote_tool_loaded: 
        try: 
            _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
            logger.info(f"set_remote_tools: {_}")
        except Exception as e:
            logger.info(f'biogen error: {e}')

# Display starters in sidebar
st.sidebar.title("Examples")
for starter in starters:
    if st.sidebar.button(starter["label"]):
        st.session_state.messages.append({"role": "user", "content": starter["message"]})
        save_session()
        st.rerun()

pid_file = os.path.join(persist_dir, f"{st.session_state.username}.process_pid")

def check_team_pid_running(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            # Check if process is running
            os.kill(pid, 0)
            return True
        except Exception as e:
            return False
    return False

## biowork ctrl
@st.dialog("Kill Task Confirmation")
def kill_task_confirm(task_id):
    if task_id is None and task_id:
        return
    st.warning("This will terminate the running task. Are you sure?")
    st.info("If you cant stop task here, please manager task at bioWorker panel")
    message = st.text_input("Optional message about why you want to stop task (can be empty):")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel"):
            st.rerun()
    with col2:
        if st.button("Confirm"):
            try:
                st.info(f"Trying to stop task {task_id}")
                response = requests.post(
                    f"{os.environ['API_URL']}/tasks/{task_id}/kill",
                    json={"message": message},
                    headers={"x-api-key": os.environ['API_KEY']}
                )
                response.raise_for_status()
                st.success("Kill signal sent.")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to kill task: {str(e)}")
st.sidebar.title("bioWorker status")
if os.environ.get('API_URL', '') != '' and os.environ.get('API_KEY', '') != '':
    st.sidebar.markdown(f"**Project ID:** {st.session_state['project_id']}")
    project_status = get_project_status(st.session_state['project_id'], API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
    ## add a placeholder for bioworker status
    bioworker_placeholder_status = st.sidebar.empty()
    if isinstance(project_status, dict):
        status = project_status.get('status', 'unknown')
        current_command = project_status.get('current_command', 'N/A')
        message_status = f"**Status:** {status.capitalize()}\n\n"
        bioworker_placeholder_status.info(message_status + f"**Current Command:**\n\n ```\n\n{current_command} \n\n```")
        if status == 'running':
            task_id = project_status.get('current_task_id')
            st.session_state.current_task_id = task_id
            if task_id and st.sidebar.button("Kill Task"):
                st.session_state.show_kill_dialog = True
    else:
        pass
    if st.sidebar.button("Stop bioWorker API Server"):
        try:
            shutdown_server(host=os.environ.get('API_URL'), api_key=os.environ.get('API_KEY'))
        except Exception as e:
            st.error(f"Failed to shutdown server: {str(e)}")
        st.session_state.api_process.kill()
        del st.session_state.api_process
        os.environ['API_URL'] = ''
        os.environ['API_KEY'] = ''
        st.session_state.api_setup_done = False
        st.sidebar.success("bioWorker API server stopped.")
        st.rerun()
    ## add a link to api url
    st.sidebar.markdown(f"[Go to bioWorker Control Panel]({os.environ.get('API_URL')})")
    ## a placeholder for llm_usage.prompt_tokens and llm_usage.completion_tokens

    llm_usage_placeholder = st.sidebar.empty()

if st.session_state.get('show_kill_dialog', False):
    kill_task_confirm(st.session_state.get('current_task_id', False))
    time.sleep(9)
    st.session_state.show_kill_dialog = False
    
# show software version as a tiny grey text at the bottom of sidebar
st.sidebar.markdown(f"<div style='position: fixed; bottom: 10px; font-size: 10px; color: grey;'>bioGen Version: {version_data}</div>", unsafe_allow_html=True)

# Initialize messages if not present
if "messages" not in st.session_state:
    st.session_state.messages = []
if "message_processed_front_ui_uuid" not in st.session_state:
    st.session_state.message_processed_front_ui_uuid = []

# Display chat messages
for message in st.session_state.messages:
    logger.debug(f"Displaying message: {message}")
    message_uuid = message.get('message_uuid', None)
    #if message_uuid and message_uuid in st.session_state.message_processed_front_ui_uuid:
    #    logger.info(f'Message uuid {message_uuid} exists in front ui, skipped')
    #    continue
    if message["role"] != "user_proxy" and message["content"].startswith("@user_proxy:") and message["content"].startswith("user_proxy:"):
        continue  # Skip displaying the calling message to user_proxy to avoid duplication
    if message["role"] == "thought":
        with st.expander(f"Thought from {get_avatar(message['source'])} {message['source']}"):
            st.markdown(message["content"])
    else:
        with st.chat_message(message["role"], avatar=get_avatar(message["role"])):
            content = message["content"]
            file_blocks = re.findall(r'<uploaded_file name="(.*?)" ext="(.*?)"\>(.*?)</uploaded_file>', content, re.DOTALL)
            cleaned_content = re.sub(r'<uploaded_file name=".*?" ext=".*?"\>(.*?)</uploaded_file>', '', content, flags=re.DOTALL)
            st.markdown(cleaned_content.strip())
            for name, ext, file_content in file_blocks:
                with st.expander(f"Uploaded file: {name}"):
                    st.code(file_content.strip(), language=ext.lower() if ext.lower() in ['python', 'json', 'html', 'md', 'txt'] else None)
    if message_uuid:
        st.session_state.message_processed_front_ui_uuid.append(message_uuid)

# Custom CSS for file uploader
st.markdown('''
<style>
[data-testid="stFileUploaderDropzone"] {
  width: 2.2rem;
  height: 2.2rem;
  background: transparent !important;
  border: none !important;
  padding: 0 !important;
  margin: 0 !important;
  min-width: unset !important;
}
[data-testid="stFileUploaderDropzone"] div,
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] p,
[data-testid="stFileUploaderDropzone"] ul {
  display: none !important;
}
[data-testid="stFileUploaderDropzone"] button {
  height: 2.2rem;
  min-width: 2.2rem;
  width: 2.2rem;
  padding: 0;
  border-radius: 50%;
  text-indent: -9999px;
  overflow: hidden;
  position: relative;
}
[data-testid="stFileUploaderDropzone"] button > span {
  display: none !important;
}
[data-testid="stFileUploaderDropzone"] button:after {
  content: "📎";
  font-size: 1.2rem;
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-indent: 0;
}
</style>
''', unsafe_allow_html=True)

# Add CSS for stop button
st.markdown('''
<style>
div.element-container button.row-widget.stButton {
  height: 2.2rem;
  min-width: 2.2rem;
  width: 2.2rem;
  padding: 0;
  border-radius: 50%;
  font-size: 1.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  background-color: transparent !important;
  border: none !important;
}
</style>
''', unsafe_allow_html=True)

def force_kill_process(pid):
    if isinstance(pid, str):
        if os.path.exists(pid):
            with open(pid, 'r') as f:
                pid_file = pid
                pid = int(f.read().strip())
        else:
            pid_file = None
            pid = int(pid)
    try:
        os.kill(pid, signal.SIGKILL)
        logger.info(f'Force killed process {pid}')
        time.sleep(3)
        try:
            os.waitpid(pid, os.WNOHANG)
        except Exception:
            pass
        try:
            os.kill(pid, 0)
            raise Exception('Process still exists after kill')
        except OSError:
            logger.info(f'Process {pid} confirmed killed')
        if pid_file and os.path.exists(pid_file):
            os.remove(pid_file)
            logger.info(f'Removed pid file {pid_file}')
    except ProcessLookupError:
        pass  # Process already terminated
    except PermissionError:
        logger.error(f'No permission to kill process {pid}')
    except Exception as e:
        logger.error(f'Failed to force kill process {pid}: {e}')

# Function to read and format uploaded file content
def read_uploaded_file(uploaded_file):
    file_name = uploaded_file.name
    file_ext = file_name.split('.')[-1].lower() if '.' in file_name else 'txt'
    
    if uploaded_file.type == "application/pdf":
        try:
            reader = pypdf.PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
        except Exception as e:
            st.error(f"Error reading PDF: {str(e)}")
            return None
    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":  # xlsx
        try:
            import openpyxl
            wb = openpyxl.load_workbook(uploaded_file)
            text = ""
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                text += f"Sheet: {sheet_name}\n"
                for row in ws.iter_rows(values_only=True):
                    text += "\t".join([str(cell) if cell is not None else "" for cell in row]) + "\n"
                text += "\n"
        except ImportError:
            st.toast("Cannot read .xlsx file: openpyxl library not installed.", icon="⚠️")
            return None
        except Exception as e:
            st.error(f"Error reading XLSX: {str(e)}")
            return None
    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":  # docx
        try:
            import docx
            doc = docx.Document(uploaded_file)
            text = "\n".join([para.text for para in doc.paragraphs])
        except ImportError:
            st.toast("Cannot read .docx file: python-docx library not installed.", icon="⚠️")
            return None
        except Exception as e:
            st.error(f"Error reading DOCX: {str(e)}")
            return None
    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":  # pptx
        try:
            import pptx
            prs = pptx.Presentation(uploaded_file)
            text = ""
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
            text = text.strip()
        except ImportError:
            st.toast("Cannot read .pptx file: python-pptx library not installed.", icon="⚠️")
            return None
        except Exception as e:
            st.error(f"Error reading PPTX: {str(e)}")
            return None
    else:
        # Text files, scripts, etc.
        try:
            text = uploaded_file.read().decode('utf-8')
        except Exception as e:
            st.error(f"Error reading file: {str(e)}")
            return None
    
    # Format the content with special markers
    formatted = f'<uploaded_file name="{file_name}" ext="{file_ext}">\n{text.strip()}\n</uploaded_file>'
    return formatted

# Initialize uploaded file tracking
if 'last_uploaded_files' not in st.session_state:
    st.session_state.last_uploaded_files = set()

if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0

# Conditional chat input with file upload and stop icon
st.session_state.init_messaged = False
placeholder_text = "Type your response here" if st.session_state.get('waiting_for_user_input', False) else "Type your message here"

def safe_load(file_path, data_dict):
    data = []
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            data = json.load(f)
    data.append(data_dict)
    with open(file_path, 'w') as f:
        json.dump(data, f)

## if team is running chage placeholder_text
if st.session_state.get('processing', False): 
    placeholder_text = "Please stop team firstly and type your response here if you need input"

user_prompt_json = os.path.join(persist_dir, f"{st.session_state.username}_input.ujson")

with st._bottom:
    col1, col2, col3, col4 = st.columns([1, 20, 1, 1])
    with col1:
        uploaded_files = st.file_uploader(
            "Upload files",
            label_visibility="collapsed",
            type=['txt', 'md', 'html', 'pdf', 'htm', 'py', 'js', 'sh', 
                  'docx', 'xlsx', 'pptx', 'java', 'c', 'cpp', 'h', 'rb', 'pl', 'php', 'go', 'rs', 'kt', 'swift', 'r', 'm', 'lua', 
                  'cs', 'ts', 'scala', 'groovy', 'perl', 'bat', 'cmd', 'ps1', 'pm', 'vb', 'f', 'f90', 'jl', 'hs', 'Rmd', 'ipynb'],
            key=f"chat_file_uploader_{st.session_state.uploader_key}",
            accept_multiple_files=True
        )
    with col2:
        message = st.chat_input(placeholder_text)
        if message:
            logger.info(f'User inputed message {message}')
            if 'automatic_start' in st.session_state:
                st.session_state.automatic_start = True
            user_message = {'role': 'user', 'message': message}
            safe_load(user_prompt_json, user_message)
            
    with col3:
        if st.session_state.get('processing', False):
            if st.button("🛑"):
                project_status = get_project_status(st.session_state.project_id, os.environ['API_URL'], os.environ['API_KEY'])
                if isinstance(project_status, dict) and project_status.get('status') == 'running':
                    st.toast("Please manually stop the ongoing task in the bioWorker panel.", icon="⚠️")
                else:
                    # Capture entire prompt history before stopping
                    st.session_state.prompt_history = "\n\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
                    save_session()
                    team_exit_file = os.path.join(persist_dir, f"{st.session_state.username}.team")
                    st.session_state.team_exit_file = team_exit_file 
                    try:
                        st.session_state.stop_team.set()
                    except (AttributeError) as e:
                        st.session_state.team_exit_file_set = team_exit_file + '_set'
                        with open(st.session_state.team_exit_file_set, 'w') as f:
                            f.write('')
                    waiting_team_stop = True
                    while not os.path.exists(st.session_state.team_exit_file) and waiting_team_stop:
                        logger.info('Stop team but team is still running, waiting')
                        st.toast("Waitting team stop", icon="ℹ️")
                        time.sleep(30)
                        waiting_team_stop = False
                    if not os.path.exists(st.session_state.team_exit_file):
                        logger.info('Stop team fail because team is still running after wait 30s')
                        st.toast("Stop team fail, team is still running after wait 30s, force stoping...", icon="ℹ️")
                        force_kill_process(pid_file)
                        #project_status = None
                        #st.rerun()
                        waiting_team_stop = False
                    else:
                        logger.info('Stop team ok')
                        os.remove(st.session_state.team_exit_file)      
                    if 'team' in st.session_state:
                        del st.session_state.team
                    st.session_state.processing = False
                    st.session_state.show_refresh_botton = True
                    st.toast("Team stopped. You can resume by providing new input.", icon="ℹ️")
    with col4:
        # team_summary_file
        @st.dialog("Refresh session")
        def _refresh_session_confirm():
            st.warning("This will terminate the running task. Are you sure?")
            st.info("Refreshing the session may help agents mitigate severe hallucinations; however, it could also lead to the loss of critical progress and prevent successful completion of the session. Do you wish to proceed?")

            clear_history = st.checkbox("Clear session history", value=False)
            automatic_start = st.checkbox("Automatically resume new session after refresh", value=True)
            st.markdown("**Note:** If you disable automatic resume, you will need to **copy** summary result provide as a new input to start the session again after refresh.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Cancel", key="cancel_refresh"):
                    st.session_state.run_summary = False
                    st.session_state.show_refresh_dialog = False 
                    st.rerun()
            with col2:
                if st.button("Confirm", key="confirm_refresh"):
                    st.session_state.run_summary = True
                    st.session_state.show_refresh_dialog = False
                    st.session_state.clear_session_content = clear_history
                    st.session_state.automatic_start = automatic_start
                    st.rerun()

        if st.session_state.get('processing', False) or st.session_state.get('show_refresh_botton', False):
            st.session_state.show_refresh_dialog = st.session_state.get('show_refresh_dialog', False)
            st.session_state.run_summary = st.session_state.get('run_summary', False)
            if st.button("🔃", key="refresh_button"):
                if isinstance(project_status, dict) and project_status.get('status') == 'running':
                    st.toast("Please manually stop the ongoing task in the bioWorker panel, and retry.", icon="⚠️")
                    st.rerun()

                try: 
                    team_summary_file = st.session_state.team_summary_file
                except Exception:
                    team_summary_file = os.path.join(persist_dir, f"{st.session_state.username}.summary_team")

                st.session_state.run_summary = False
                st.session_state.show_refresh_dialog = True
                st.session_state.user_confirmed_summary = False
                st.session_state.user_required_summary = True
                st.rerun()

            if st.session_state.show_refresh_dialog:
                try: 
                    team_summary_file = st.session_state.team_summary_file
                except Exception:
                    team_summary_file = os.path.join(persist_dir, f"{st.session_state.username}.summary_team")
                    st.session_state.team_exit_file = os.path.join(persist_dir, f"{st.session_state.username}.team")
                    st.session_state.team_summary_file = team_summary_file
                _refresh_session_confirm()

            if st.session_state.run_summary:
                try:
                    st.toast('Please wait up to one min')
                    logger.info('start refresh session')
                    with open(st.session_state.team_exit_file + '_set', 'w') as f:
                        f.write('') 
                    with open(st.session_state.team_summary_file, 'w') as f:
                        f.write('')
                    time.sleep(10)
                    logger.info('status files created, waiting team stop')
                    if not os.path.exists(st.session_state.team_exit_file) and check_team_pid_running(pid_file):
                        st.toast('Fail to refresh session, force restart')
                        pid_file = os.path.join(persist_dir, f"{st.session_state.username}.process_pid")
                        force_kill_process(pid_file)
                        st.session_state.run_summary = False
                        st.session_state.show_refresh_dialog = False
                        #st.rerun()  
                        logger.info('team still running after wait, force killed')
                    else:
                        st.toast('restarting session')
                        st.session_state.run_summary = False
                        st.session_state.show_refresh_dialog = False
                        #st.rerun()
                    logger.info('team stopped, creating new team with summary')
                except Exception as e:
                    st.error(f"Failed to refresh session: {str(e)}")
                    
                #agfile = os.path.join(persist_dir, f"{st.session_state.username}.json")

                st.session_state.run_summary = False
                st.session_state.show_refresh_dialog = False
                st.rerun()
            
        

# Handle sending message, including file if uploaded
if message is not None:
    full_message = message.strip() if message else ""
    file_contents = []
    
    logger.info('Process user input')

    if uploaded_files:
        new_files = [f for f in uploaded_files if f.name not in st.session_state.last_uploaded_files]
        for f in new_files:
            content = read_uploaded_file(f)
            if content:
                file_contents.append(content)
            st.session_state.last_uploaded_files.add(f.name)
        if new_files:
            st.toast("For better file handling, please refer to our documentation on using RAG instead of direct uploads.", icon="ℹ️", duration=19)

    if file_contents:
        full_message += "\n\n" + "".join(file_contents) if full_message else "".join(file_contents)

    if full_message:  # Only proceed if there's content (ignore pure empty submits)
        if st.session_state.get('waiting_for_user_input', False):
            logger.info('User message to file')
            with open(st.session_state.input_file, 'w') as f:
                f.write(full_message)
            st.session_state.messages.append({"role": "user", "content": full_message})
            del st.session_state.waiting_for_user_input
            save_session()
            st.session_state.uploader_key += 1
            st.rerun()
        else:
            logger.info('User message to session_state')
            st.session_state.messages.append({"role": "user", "content": full_message, "processed": False})
            if st.session_state.get('init_processing', False): 
                st.session_state.processing = False
                st.session_state.init_processing = False
            save_session()
            if not st.session_state.init_messaged:
                st.info("Initialize the session. If you have loaded memory, this may take up to five minutes.")
                st.session_state.init_messaged = True
            st.session_state.uploader_key += 1
            st.rerun()
        message = None
    else:
        # If empty message and no new file, do nothing
        pass

class Reward:
    def __init__(
        self,
        initial_reward: float,
        decay_rate: float = 0.6,
        slow_decay_rate: float = 0.99,
        recovery_step: float = -1,
        cooldown_period: int = 10,
        window_a: int = 15,
        min_triggers_a: int = 3,
        window_b: int = 30,
        min_pattern_len: int = 3
    ):
        self.initial_reward = initial_reward
        self.decay_rate = decay_rate
        self.slow_decay_rate = slow_decay_rate
        self.recovery_step = recovery_step
        self.cooldown_period = cooldown_period
        self.window_a = window_a
        self.min_triggers_a = min_triggers_a
        self.window_b = window_b
        self.min_pattern_len = min_pattern_len
        if self.recovery_step < 0:
            recovery_step = 0.1
        self.reset()

    def reset(self) -> None:
        self.current_reward = float(self.initial_reward)
        self.clock = 0
        self.history: Deque[Tuple[int, str]] = collections.deque()
        self.cooldown_until = 0

    def timer(self) -> None:
        self.clock += 1

    def __call__(self, category: str = 'default') -> int:
        self.history.append((self.clock, category))
        self._maintain_history()
        self._evaluate_recovery()
        
        output_reward = round(self.current_reward)
        
        if output_reward == 0:
            self.current_reward *= self.slow_decay_rate
        else:
            self.current_reward *= self.decay_rate
            
        return output_reward

    def _maintain_history(self) -> None:
        while self.history and self.history[0][0] <= self.clock - self.window_b:
            self.history.popleft()

    def _evaluate_recovery(self) -> None:
        if self.clock <= self.cooldown_until:
            return

        recent_triggers_a = sum(1 for tick, _ in self.history if tick > self.clock - self.window_a)
        if recent_triggers_a < self.min_triggers_a:
            return

        recent_b = list(self.history)
        max_len = 0
        n = len(recent_b)

        for i in range(n - self.min_pattern_len + 1):
            cat = recent_b[i][1]
            if recent_b[i + 1][1] != cat:
                continue

            interval = recent_b[i + 1][0] - recent_b[i][0]
            curr_len = 2
            
            for j in range(i + 2, n):
                if recent_b[j][1] == cat and recent_b[j][0] - recent_b[j - 1][0] == interval:
                    curr_len += 1
                else:
                    break
                    
            if curr_len >= self.min_pattern_len and recent_b[i + curr_len - 1][0] == self.clock:
                max_len = max(max_len, curr_len)

        if max_len >= self.min_pattern_len:
            recovery_amount = self.initial_reward * (max_len * self.recovery_step)
            self.current_reward = min(self.initial_reward, self.current_reward + recovery_amount)
            self.cooldown_until = self.clock + self.cooldown_period

# Function to process the task in background thread
st.session_state['llm_usage'] = {}
def process_task(user_message, log_file, team, stop_team, force_stop, team_status_file = None, team_exit_file = None, team_summary_file = None, max_content=1000, load_history=True, sucessfulExecutate_reward = 0):
    def _create_file(file):
        if file:
            with open(file, 'w') as f:
                pass
    def _json_safedump(obj, fp, *, uuid=None, **kwargs):
        if not isinstance(obj, dict):
            raise ValueError("obj must be a dict")
        if uuid is None:
            uuid = str(uuid4.uuid4())
        obj_with_meta = {**obj, "message_uuid": uuid, "message_processed": False}
        json.dump(obj_with_meta, fp, **kwargs)
    def _exit_team(wait_time = 10): 
        st.session_state.cancellation_token.cancel()
        time.sleep(wait_time)
        return
    
    def _stop_team_set(team_exit_file):
        if os.path.exists(team_exit_file+'_set'):
            stop_team.set()
            os.remove(team_exit_file+'_set')
    
    if 'project_id' not in st.session_state:
        ## init project id
        project_id = asyncio.run(execute_shell_command_via_api(command=''))
        st.session_state['project_id'] = project_id
        if remote_tool_loaded: 
            try: 
                _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'], sucessfulExecutate_reward = 10)
                logger.info(f"set_remote_tools: {_}")
            except Exception as e:
                logger.info('biogen error: {e}')
    st.session_state.cancellation_token = CancellationToken()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    max_retries = 5
    retries = 0
    # Collect history from previous messages
    history = []
    if load_history:
        for msg in st.session_state.get('messages', []):
            if 'processed' in msg and not msg['processed']:
                continue  # Skip the current unprocessed message
            source = msg.get('source', msg['role'])
            try:
                history.append(TextMessage(content=msg['content'], source=source))
            except Exception as e:
                logger.error(f"Failed to append message to history: {str(e)}")
    task_messages = history + [TextMessage(content=user_message, source="user")]
    task_messages_num = 0
    
    ## sucessful reward
    #class DiminishingReward:
    #    def __init__(self, initial_reward: float) -> None:
    #        self.initial_reward = initial_reward
    #        self.call_count = 0     
    #    def __call__(self) -> float:
    #        """Return current reward and increment call counter."""
    #        reward = round(self.initial_reward / (1 + self.call_count), 0)
    #        self.call_count += 1
    #        return reward       
    #    def reset(self) -> None:
    #        """Reset call count to zero for reuse."""
    #        self.call_count = 0
        
    reward = Reward(sucessfulExecutate_reward)
    
    while retries <= max_retries:
        try:
            async_gen = team.run_stream(
                task=task_messages,
                cancellation_token=st.session_state.cancellation_token
            )
            current_source = None
            current_content = ""
            time_out=60
            try:
                while True:
                    _stop_team_set(team_exit_file)
                    if stop_team.is_set():
                        ## stop team
                        st.session_state.cancellation_token.cancel()
                        if team_status_file:
                            save_agents(team=team, file=team_status_file)
                    
                    if force_stop.is_set():
                        st.session_state.cancellation_token.cancel()
                        time.sleep(10)
                        _create_file(team_exit_file)
                        return 
                        
                    msg = loop.run_until_complete(anext(async_gen))
                    #msg = loop.run_until_complete(asyncio.wait_for(anext(async_gen), timeout=time_out))
                    time_out = 60
                    ## print msg type
                    logger.info(f"====> Received message of type: {type(msg)} from source: {getattr(msg, 'source', 'N/A')}")
                    if msg is None:
                        break
                    ## update llm_usage
                    try:
                        llm_usage_current = msg.usage
                        ## llm_usage.prompt_tokens llm_usage.completion_tokens
                        completion_token = llm_usage_current.get('completion_tokens', None)
                        prompt_token = llm_usage_current.get('prompt_tokens', None)
                        logger.info(f"LLM usage: prompt_tokens: {prompt_token}, completion_tokens: {completion_token}, total_tokens: {llm_usage_current.get('total_tokens', None)}")
                    except Exception as e:
                        logger.error(f"Failed to process message: {str(e)}")
                        logger.error(str(msg))
                    try:
                        if msg.source == "user":
                            logger.info(f"<==== User message received")
                            continue
                        msg_content = msg.content
                        if "user_proxy:" in msg_content:
                            continue
                        #bioworker_placeholder.empty()
                        if msg.source == "safety_checker_agent":
                            logger.info(f"<==== Safety checker message received")
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'toast',
                                                  'message': f"Start executing command\nView progression at {os.environ.get('API_URL')} with your API key",
                                                  'icon': "ℹ️", "time": 10}, f)
                                f.write('\n')
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'toast', 'message': "This page will auto update after command execution is complete.",
                                         'icon': "ℹ️", "time": 10}, f)
                                f.write('\n')
                    except Exception as e:
                        logger.error(f"Failed to process message: {str(e)}")
                        pass
                    if isinstance(msg, (openai.RateLimitError, BadRequestError, APITimeoutError, APIConnectionError, openai.NotFoundError)):
                        logger.error(f"Failed to process message: {str(e)}")
                        raise msg
                    if isinstance(msg, TaskResult):
                        termination_msg = "Task terminated. "
                        logger.info(f"<==== TaskResult message received")
                        if msg.stop_reason:
                            termination_msg += msg.stop_reason
                        with open(log_file, 'a') as f:
                            _json_safedump({'type': 'message', 'role': "system", "content": termination_msg}, f)
                            f.write('\n')
                        _create_file(team_exit_file)
                        save_agents(team=team, file=team_status_file)
                        break
                    elif isinstance(msg, ThoughtEvent):
                        logger.info(f"<==== ThoughtEvent message received")
                        if current_content:
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                        thought_content = msg.content
                        with open(log_file, 'a') as f:
                            _json_safedump({'type': 'message', 'role': "thought", "content": thought_content, "source": msg.source}, f)
                            f.write('\n')
                        current_source = None
                        current_content = ""
                    elif isinstance(msg, ModelClientStreamingChunkEvent) or isinstance(msg, TextMessage) or isinstance(msg,
                                                                                                                       GroupChatMessage) or isinstance(msg, MultiModalMessage):
                        logger.info(f"<==== Text/Streaming message received from {msg.source}")
                        if msg.source != current_source:
                            if current_content:
                                with open(log_file, 'a') as f:
                                    _json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                    f.write('\n')
                            current_source = msg.source
                            current_content = ""
                        if isinstance(msg, ModelClientStreamingChunkEvent):
                            current_content += msg.content
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'stream_update', 'source': current_source, 'content': current_content}, f)
                                f.write('\n')
                        elif isinstance(msg, TextMessage) or isinstance(msg, GroupChatMessage):
                            current_content += msg.content + "\n"
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                            if task_messages_num > max_content or 'SUMMARYSUMMARY' in current_content:
                                ## create summary file
                                with open(team_summary_file, 'w') as f:
                                    pass
                                with open(team_summary_file + '_no_user_confirm', 'w') as f:
                                    pass
                                logger.info('max_chat_message_num reached')
                                _exit_team()
                                _create_file(team_exit_file)
                                save_agents(team=team, file=team_status_file)
                                reward.reset()
                                with open(log_file, 'a') as f:
                                    _json_safedump({'type': 'message', 'role': 'system', "content": 'Max chat message number reached, will summarise message and resume session'}, f)
                                    f.write('\n')
                                #raise BadRequestError('setted max content number reached, raise error')
                        elif isinstance(msg, MultiModalMessage):
                            logger.info(f"<==== MultiModalMessage received from {msg.source}")
                    elif isinstance(msg, ToolCallRequestEvent):
                        logger.info(f"<==== ToolCallRequestEvent message received")
                        with open(log_file, 'a') as f:
                            _json_safedump({'type': 'toast',
                                              'message': f"Start executing command\nView progression at {os.environ.get('API_URL')} with your API key",
                                              'icon': "ℹ️", "time": 999}, f)
                            f.write('\n')
                        with open(log_file, 'a') as f:
                            _json_safedump({'type': 'toast', 'message': "This page will auto update after command execution is complete.",
                                     'icon': "ℹ️", "time": 999}, f)
                            f.write('\n')
                        time_out = float('inf')
                    elif isinstance(msg, ToolCallExecutionEvent) or isinstance(msg, ToolCallSummaryMessage):
                        logger.info(f"<==== ToolCallExecutionEvent message received")
                        try:
                            output = msg.content[0].content
                        except:
                            output = str(msg.content)
                        output = f"Execution result:\n```\n{output}\n```"
                        with open(log_file, 'a') as f:
                            _json_safedump({'type': 'message', 'role': "system", "content": output}, f)
                            f.write('\n')
                        if not "Error" in output:
                            reward_value = reward('Tool_event')
                            task_messages_num = max(task_messages_num - reward_value, 0)
                            logger.info(f"Reward for {msg.source}: {reward_value}, current task messages num: {task_messages_num}")
                        time_out = float('inf')
                    elif isinstance(msg, UserInputRequestedEvent):
                        logger.info(f"<==== UserInputRequestedEvent message received")
                        if current_content:
                            with open(log_file, 'a') as f:
                                _json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                            current_content = ""
                        # st.info(f"User input required: ")  # Can't use st in thread
                        time_out = float('inf')
                    task_messages_num = task_messages_num + 1
            
            except (asyncio.CancelledError, GeneratorExit):
                logger.info("Task cancelled")
                with open(log_file, 'a') as f:
                    _json_safedump({'type': 'message', 'role': "system", "content": "Task stopped by user. You can resume by providing new input."}, f)
                    f.write('\n')
                    #json.dump({'type': 'done'}, f)
                    #f.write('\n')
                if 'stop_team' in st.session_state:
                    st.session_state.stop_team.clear()
                _exit_team()
                _create_file(team_exit_file)
                save_agents(team=team, file=team_status_file)
                return

            if current_content:
                with open(log_file, 'a') as f:
                    _json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                    f.write('\n')
            _exit_team()
            _create_file(team_exit_file)
            save_agents(team=team, file=team_status_file)
            return

        except StopAsyncIteration:
            pass
        except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.APIStatusError) as e:
            retries += 1
            error_message = f"OpenAI error: {str(e)}. Retry attempt {retries}/{max_retries}."
            with open(log_file, 'a') as f:
                _json_safedump({'type': 'message', 'role': "system", "content": error_message}, f)
                f.write('\n')
            if retries > max_retries:
                error_message = f"Maximum retries exceeded. Please check your connection or API limits. To resume, you can send your message again or continue the conversation."
                with open(log_file, 'a') as f:
                    _json_safedump({'type': 'message', 'role': "system", "content": error_message}, f)
                    f.write('\n')
                _exit_team()
                _create_file(team_exit_file)
                save_agents(team=team, file=team_status_file)
                return
            wait_time = 30 * (2 ** (retries - 1)) + random.uniform(0, 10)  # Exponential backoff with jitter, starting from 30s
            time.sleep(wait_time)
        except (BadRequestError, openai.BadRequestError) as e:
            logger.info(f'output tocken {e}')
            _json_safedump({'type': 'message', 'role': "system", "content": f'Out of content number error: {e}, Will summary content and rerun'}, f)
            if team_summary_file:
                _exit_team()
                _create_file(team_exit_file)
                _create_file(team_summary_file)
                save_agents(team=team, file=team_status_file)
        except Exception as e:
            with open(log_file, 'a') as f:
                _json_safedump({'type': 'message', 'role': "system", "content": f"Unexpected error: {str(e)}"}, f)
                f.write('\n')
            exception_str = str(e)
            if 'Queue' in exception_str  or 'loop' in exception_str or 'The team is already running' in exception_str:
                logger.info('Queue error found, exit task')
                retries = max_retries + 1
            if retries > max_retries:
                error_message = f"Maximum retries exceeded. Please check your connection or API limits. To resume, you can send your message again or continue the conversation."
                with open(log_file, 'a') as f:
                    json.dump({'type': 'message', 'role': "system", "content": error_message}, f)
                    f.write('\n')
                     
                save_agents(team=team, file=team_status_file)
                _exit_team()
                _create_file(team_exit_file)
                return
            wait_time = 30 * (2 ** (retries - 1)) + random.uniform(0, 10)  # Exponential backoff with jitter, starting from 30s
            time.sleep(wait_time)


# Process pending user messages
team_exit_file = os.path.join(persist_dir, f"{st.session_state.username}.team")
team_summary_file = os.path.join(persist_dir, f"{st.session_state.username}.summary_team")
team_summary = os.path.exists(team_summary_file)
team_summary_no_user_confirm = os.path.exists(team_summary_file + '_no_user_confirm')
pid_file = os.path.join(persist_dir, f"{st.session_state.username}.process_pid")
if "messages" in st.session_state and st.session_state.messages:
    #logger.info('Process user message to team')
    last_user_message = next(
        (msg for msg in reversed(st.session_state.messages) if msg["role"] == "user" and not msg.get("processed")),
        None)
    
    if last_user_message:
        logger.info(f'Found unprocessed user message: {last_user_message["content"][:50]}...')
        logger.info(f'If expr: {(last_user_message is not None or team_summary)} and {(not st.session_state.get("processing", False) or os.path.exists(team_exit_file) or not check_team_pid_running(pid_file))}')
        logger.info(f'Pid state check:{check_team_pid_running(pid_file)}')
    #logger.debug(f"Processing status: {st.session_state.get('processing', False)}")
    if (last_user_message is not None or team_summary) and (not st.session_state.get('processing', False) or os.path.exists(team_exit_file) or not check_team_pid_running(pid_file)):
        logger.info('Starting new processing thread for user message')
        if last_user_message:
            user_message = last_user_message["content"]
        else:
            last_user_message = {"content": "Please continue tasks", "processed": False}
            user_message = 'Please continue tasks'
        last_user_message["processed"] = True
        save_session()
        st.session_state.processing = True
        st.session_state.processing_start_time = time.time()  # Record start time for elapsed counter
        st.session_state.last_save_time = time.time()  # Initialize last save time
        # Inject JS to keep browser tab awake and refresh every 10 minutes during long waits
        st.components.v1.html("""
            <script>
                setInterval(() => {
                    console.log('Keeping connection alive');
                }, 5000);
                setInterval(() => {
                    location.reload();
                }, 600000); // 10 minutes
            </script>
        """, height=0)
        st.session_state.stop_team = multiprocessing.Event()
        st.session_state.force_stop = multiprocessing.Event()
        stop_team_event = st.session_state.stop_team
        force_stop_team_event = st.session_state.force_stop
        agent_status_file = os.path.join(persist_dir, f"{st.session_state.username}.agjson")
        st.session_state.agent_status_file = agent_status_file
        team_exit_file = os.path.join(persist_dir, f"{st.session_state.username}.team")
        st.session_state.team_exit_file = team_exit_file 
        pid_file = os.path.join(persist_dir, f"{st.session_state.username}.process_pid")
        st.session_state.pid_file = pid_file
        if os.path.exists(team_exit_file) or not check_team_pid_running(pid_file):
            if 'team' in st.session_state: 
                del st.session_state.team
            logger.info('Remove existing team exit file before starting new task')
            try: 
                os.remove(team_exit_file)
            except Exception as e:
                logger.info(f'Failed to remove team exit file: {e}')
        team_summary_file = os.path.join(persist_dir, f"{st.session_state.username}.summary_team")
        st.session_state.team_summary_file = team_summary_file
        st.session_state.max_content = sys_config.get('max_content', 1000)
        st.session_state.max_summary_content = sys_config.get('max_summary_content', 10000)
        max_summary_content = st.session_state.max_summary_content
        if st.session_state.max_content != 1000: 
            logger.info(f'set max conent number to {st.session_state.max_content}')
        if os.path.exists(team_summary_file):
            logger.info('Remove existing team summary file before starting new task')
            os.remove(team_summary_file)
            team_summary = True
        else:
            team_summary = False
        if os.path.exists(team_summary_file + '_no_user_confirm'):
            logger.info('Remove existing team summary no_user_confirm file before starting new task')
            os.remove(team_summary_file + '_no_user_confirm')
            team_summary_no_user_confirm = True
        else:
            team_summary_no_user_confirm = False
        print(f"remote_tool_loaded: {remote_tool_loaded} after create team")
        # Recreate team if not present
        if 'team' not in st.session_state:
            st.session_state.team = create_team(file=st.session_state.agent_status_file, team_summary=team_summary)
            if remote_tool_loaded: 
                try: 
                    #def set_remote_tools(tools_dict: dict, project_id: str, api_base_url: str, api_key: str, working_dir: str = None) -> dict:
                    _ = set_remote_tools(tools_dict = remote_tool_detail, project_id = os.environ['PROJECT_ID'], api_base_url = os.environ['API_URL'], api_key = os.environ['API_KEY'])
                    print(f"set_remote_tools: {_}")
                except Exception as e:
                    print(f'biogen error: {e}')
                # Update log_file and input_file
            load_history = (not team_summary and not st.session_state.get('finish_summary', False))
            if load_history:
                st.session_state.finish_summary = False
            st.session_state.load_history = load_history
            if team_summary:
                ag_file = os.path.join(persist_dir, f"{st.session_state.username}.agjson")
                if os.path.exists(ag_file):
                    os.remove(ag_file)
                session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
                # get config
                max_summary_content = sys_config.get('max_summary_content', 10000)
                user_prompt_json = os.path.join(persist_dir, f"{st.session_state.username}_input.ujson")
                user_prompt_history = None
                if os.path.exists(user_prompt_json):
                    with open(user_prompt_json, 'r') as json_f:
                        user_prompt_history = json.load(json_f)[0]['message']
                content_summary = bg_summary.run_summary(session_file, content_summary_model, max_summary_content, user_prompt_history)
                content_summary = """==============User Orginal task============\n""" + str(user_prompt_history) +"""\mCurrent Processing Summary:\n""" + content_summary + '\n'
                team_summary = False
                user_message = content_summary + '\nNew user task is ' + user_message
                st.session_state.chat_summary_message = content_summary
                
                @st.dialog("Edit Chat Summary", width="large")
                def edit_chat_summary():
                    current = st.session_state.get("chat_summary_message", "")

                    edited = st.text_area(
                        "Edit the chat summary:",
                        value=current,
                        height=300,
                        key="edit_summary_textarea"
                    )

                    if st.button("Confirm", type="primary", use_container_width=True):
                        st.session_state.chat_summary_message = edited
                        st.session_state.user_confirmed_summary = True
                        logger.info('User confirmed chat summary')
                        st.rerun()


                logger.info(f"if expr: {not st.session_state.get('user_confirmed_summary', False)} and {st.session_state.get('user_required_summary', False)}")
                
                if not st.session_state.get("user_confirmed_summary", False) and st.session_state.get("user_required_summary", False):
                    #edit_chat_summary()
                    logger.info('Waiting for user to confirm chat summary')
                    if not st.session_state.get("user_confirmed_summary", False):
                        #st.stop()
                        st.session_state.user_confirmed_summary = True
                        pass
                    else: 
                        logger.info('User confirmed chat summary')
                    #st.stop()
                else:
                    logger.info('No need to confirm chat summary, proceeding')
                if st.session_state.get("user_confirmed_summary", False) or not st.session_state.get("user_required_summary", False):
                    if "user_required_summary" in st.session_state:
                        del st.session_state.user_required_summary
                    user_message = st.session_state.get("chat_summary_message", content_summary)
                    def _json_safedump(obj, fp, *, uuid=None, **kwargs):
                        if not isinstance(obj, dict):
                            raise ValueError("obj must be a dict")
                        if uuid is None:
                            uuid = str(uuid4.uuid4())
                        obj_with_meta = {**obj, "message_uuid": uuid, "message_processed": False}
                        json.dump(obj_with_meta, fp, **kwargs)
                    chat_content = {"role": "system", "content": f"Previous conversation content summarized as: \n```{content_summary}```\n. Continue to work on the task."}
                    with open(st.session_state.log_file, 'a') as f:
                        _json_safedump(chat_content, f)
                    st.session_state.messages.append(chat_content)
                    #logger.info(f'Task summary: {user_message}')
                    st.toast("Chat summary applied. Continuing with the task. Please Wait more times for reload session", icon="✅", duration=60)
                    logger.info("Chat summary applied")
                    st.session_state.finish_summary = True
                    st.session_state.processing = True
                st.session_state.user_confirmed_summary = False
        logger.info(f'Task process if expr {not team_summary} or {st.session_state.get("finish_summary", False)}')
        if not team_summary or st.session_state.get('finish_summary', False):
            logger.info('Starting thread')
            logger.info(f'Init user message_length {len(user_message)}')
            ## reset stop team and force_stop
            st.session_state.stop_team = multiprocessing.Event()
            st.session_state.force_stop = multiprocessing.Event()
            if os.path.exists(team_exit_file):
                os.remove(team_exit_file)
            if os.path.exists(team_exit_file + '_set'):
                os.remove(team_exit_file + '_set')
            if os.path.exists(st.session_state.agent_status_file):
                os.remove(st.session_state.agent_status_file)
            if os.path.exists(pid_file):
                os.remove(pid_file)
            if os.path.exists(st.session_state.log_file):
                with open(st.session_state.log_file, 'w') as f:
                    pass
            if os.path.exists(st.session_state.team_summary_file):
                os.remove(st.session_state.team_summary_file)
                
            if os.path.exists(team_summary_file + '_no_user_confirm'):
                os.remove(team_summary_file + '_no_user_confirm')
            
            if st.session_state.get('clear_session_content', False):
                # move session file to backup
                session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
                backup_file = os.path.join(persist_dir, f"{st.session_state.username}_{int(time.time())}.json")
                if os.path.exists(session_file):
                    os.rename(session_file, backup_file)
                    logger.info(f'Session file moved to backup: {backup_file}')
                st.session_state.clear_session_content = False
                # clear messages history in st.session_state
                st.session_state.messages = []
                ## add summary message
                if st.session_state.get("chat_summary_message", ""):
                    chat_content = {"role": "system", "content": f"Previous conversation content summarized as: \n```{st.session_state.get('chat_summary_message', '')}```\n. Continue to work on the task."}
                    st.session_state.messages.append(chat_content)
                    logger.info('Session content cleared, summary message added to new session')
                    st.info('Previous session content cleared. Please refresh web page to see the changes.')
                save_session()
            
            logger.info(f'st.session_state.automatic_start: {st.session_state.get("automatic_start", True)}, team_summary: {team_summary}')
            if st.session_state.get('automatic_start', True): 
                sucessfulExecutate_reward = sys_config.get('sucessfulExecutate_reward', 10)
                #reward = Reward(sucessfulExecutate_reward)
                process_p = Process(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward),
                            daemon=True)
                process_p.start()
                logger.info(f'Thread started, st.session_state: {st.session_state.get("processing", False)}, pid: {process_p.pid}')
                st.toast('Team starting', icon="✅", duration=60)
                with open(pid_file, 'w') as f:
                    f.write(str(process_p.pid))
                if 'init_processing' in st.session_state: 
                    st.session_state.init_processing = False
                if team_summary or st.session_state.get("finish_summary", False):
                    message = 'Continue'
            else:
                logger.info('Automatic start disabled, waiting for user to start processing')
                st.toast('Automatic start disabled. Please Copy summary message, edit if need, paste in input box, submit message to resume session.', icon="ℹ️", duration=9000)
            st.rerun()
    else: 
        if last_user_message:
            last_user_message["processed"] = True

# Polling logic during processing or pending input
if st.session_state.get('processing', False):
    waiting_placeholder = st.empty()  # Placeholder for dynamic waiting message
    with waiting_placeholder.container():
        st.info("The agent is processing your request. Please wait until further input is required.")
    updated = False
    
    if 'message_processed_uuid' not in st.session_state.keys():
        st.session_state.message_processed_uuid = []

    # Process log file
    if os.path.exists(st.session_state.log_file):
        with open(st.session_state.log_file, 'r') as f:
            lines = f.readlines()
        if lines:
            for line in lines:
                try:
                    item = json.loads(line)
                    message_uuid = item.get('message_uuid', None)
                    if message_uuid and message_uuid in st.session_state.message_processed_uuid:
                        logger.info(f'Processed message uuid {message_uuid}, skipped')
                        continue
                    else:
                        st.session_state.message_processed_uuid.append(message_uuid)
                    if item.get('type') == 'prompt':
                        prompt_type = item['prompt_type']
                        if prompt_type == 'input':
                            content = item['content']
                            if content.startswith("@user_proxy:"):
                                content = content[len("@user_proxy:"):].strip()  # Strip "@user_proxy:" from prompt if present
                            if not st.session_state.messages or st.session_state.messages[-1].get('content') != content:
                                st.session_state.messages.append({"role": "user_proxy", "content": content})
                            st.session_state.waiting_for_user_input = True
                            updated = True
                        # Handle 'action' if needed in future
                    elif item.get('type') == 'toast':
                        duration_time = 10
                        if 'time' in item and item['time']:
                            duration_time = max(30, item['time'])
                        st.toast(item["message"], icon=item.get('icon'), duration=duration_time)
                        updated = True
                    elif item.get('type') == 'stream_update':
                        if st.session_state.messages and st.session_state.messages[-1].get('role') == item['source']:
                            st.session_state.messages[-1]['content'] = item['content']
                        else:
                            st.session_state.messages.append({"role": item['source'], "content": item['content'], "source": item['source']})
                        updated = True
                    elif item.get('type') == 'done':
                        if 'stop_team' in st.session_state:
                            st.session_state.stop_team.clear()
                        updated = True
                    elif item.get('type') == 'message':
                        content = item['content']
                        if not st.session_state.messages or not (st.session_state.messages[-1].get('role') == item['role'] and st.session_state.messages[-1].get('content') == content):
                            st.session_state.messages.append({"role": item['role'], "content": content, "source": item.get('source')})
                        updated = True
                    if item.get('message_uuid', None):
                        message_uuid = item.get('message_uuid', None)
                        st.session_state.message_processed_uuid.append(message_uuid)
                        if item.get('type') == 'message':
                            st.session_state.messages[-1] = {**st.session_state.messages[-1], "message_uuid": message_uuid, "message_processed": False}
                except json.JSONDecodeError:
                    pass
            #save_session()
            open(st.session_state.log_file, 'w').close()
            updated = True

    # Update bioworker status
    try:
        project_status = get_project_status(st.session_state['project_id'], API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
        if isinstance(project_status, dict):
            status = project_status.get('status', 'unknown')
            current_command = project_status.get('current_command', 'N/A')
            message_status = f"**Status:** {status.capitalize()}\n\n"
            bioworker_placeholder_status.info(message_status + f"**Current Command:**\n\n ```\n\n{current_command} \n\n ```")
        else:
            pass
    except Exception as e:
        pass

    if updated:
        logger.info('Saving session file')
        save_session()
        st.session_state.last_save_time = time.time()

    if updated:
        st.rerun()
    else:
        # Dynamic waiting indicator to keep WebSocket active
        elapsed = time.time() - st.session_state.get('processing_start_time', time.time())
        with waiting_placeholder.container():
            if elapsed - st.session_state.get('last_st_time', 0) > 5:
                st.session_state.last_st_time = elapsed
                #st.info(f"The agent is processing your request (elapsed: {int(elapsed)} seconds). Please wait until further input is required.")
                st.info(f"Execution time elapsed: {int(elapsed)} seconds")
        # Periodic save every 10 minutes even if no update
        if time.time() - st.session_state.get('last_save_time', 0) > 600:  # 600 seconds = 10 minutes
            save_session()
            st.session_state.last_save_time = time.time()
        time.sleep(0.5)
        #if 'last_refresh_time' not in st.session_state: 
        #    st.session_state.last_refresh_time = time.time()
        #if time.time() - st.session_state.last_refresh_time > 1800:
        #    streamlit_js_eval(js_expressions="parent.window.location.reload()")
        if 'last_rerun_time' not in st.session_state:
            st.session_state.last_rerun_time = time.time()
        #if time.time() - st.session_state.last_rerun_time > st.session_state.get('rerun_time', 1):
        #    st.session_state.rerun_time = 1
        st.rerun()