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
from queue import Queue, Empty

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage, ModelClientStreamingChunkEvent, ToolCallExecutionEvent, \
    ToolCallRequestEvent, UserInputRequestedEvent, ThoughtEvent
from autogen_agentchat.teams._group_chat._events import GroupChatMessage

sys.path.append('/mnt/e/software/bioGen')
sys.path.append('/mnt/e/software/bioGen/bioGen')

import sys, os
import streamlit as st
from bioGen.biogen import *
import asyncio
from typing import cast
from streamlit_cookies_manager import EncryptedCookieManager

# Define starters similar to Chainlit's set_starters
starters = [
    {
        "label": "RNA-seq",
        "message": '''
Objective: Perform RNA-Seq analysis, including transcript abundance quantification and differential expression analysis (DEA), using STAR for alignment and featureCounts for quantification. Store results in /RNA-seq.
Expected Outputs:

Aligned BAM files with corresponding indices.
Transcript abundance counts.
Differential Expression Analysis (DEA) using DESeq2, performed if grouping information is provided or can be inferred from FASTQ file names.

User Input Requirements:Please provide the following details to proceed with the analysis:

FASTQ File Location:

Specify the directory path containing your RNA-Seq FASTQ files.

Reference Genome and Annotation:

Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
Annotation File (GTF/GFF3 format): Provide the full path to the gene annotation file.
Optional: If needed, download resources from Ensembl or UCSC Genome Browser. For example, use wget to retrieve files like Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz or Homo_sapiens.GRCh38.108.gtf.gz from Ensembl.

Grouping Information for DEA:

Provide Grouping Information: Submit experimental group details (e.g., 'control', 'treatment') in a comma-separated list or table linking each FASTQ file to a group.
Infer from FASTQ File Names: If group information can be derived from FASTQ file names (e.g., sample1_control_R1.fastq.gz, sample2_treatment_R1.fastq.gz), describe the naming convention.

Optional Parameters:

Number of Threads: Specify the number of CPU threads available to optimize processing speed.

Instructions:

Provide the requested information to initiate the analysis.
After receiving the inputs, the system will summarize the provided details, perform the analysis, and store results in /RNA-seq.
Upon completion, confirm with the user if additional tasks are needed.
''',
        "icon": "http://nondisk.136138189.xyz:2086/f/9yHN/ngs.png",
    },
    {
        "label": "WGS analysis",
        "message": "Explain superconductors like I'm five years old.",
        "icon": "http://nondisk.136138189.xyz:2086/f/34Cd/wgs.png",
    },
    {
        "label": "ATAC-seq",
        "message": "Write a script to automate sending daily email reports in Python, and walk me through how I would set it up.",
        "icon": "http://nondisk.136138189.xyz:2086/f/GNFq/Transposase_ATAC.svg",
    },
]


def create_user_input_func(prompt_queue, response_queue):
    def user_input_func(prompt: str) -> str:
        prompt_queue.put(('input', prompt))
        return response_queue.get()

    return user_input_func


def create_user_action_func(prompt_queue, response_queue):
    def user_action_func(prompt: str) -> str:
        prompt_queue.put(('action', prompt))
        return response_queue.get()

    return user_action_func


# Tasks string
tasks = '''
You are a knowledgeable bioinformatics assistant. You run in a Linux environment.
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
'''.format(work_dir_env=os.environ.get('WORK_DIR', ''))

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
persist_dir = os.path.join(work_dir_env, 'user_sessions')
os.makedirs(persist_dir, exist_ok=True)

cookies = EncryptedCookieManager(
    prefix="biogen_",
    password=os.environ.get("COOKIE_PASSWORD", "your_secure_long_password_here")
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
    if os.path.exists(session_file):
        with open(session_file, 'r') as f:
            data = json.load(f)
            st.session_state.messages = data.get('messages', [])
            st.session_state.prompt_history = data.get('prompt_history', "")
            if 'project_id' in data:
                st.session_state.project_id = data['project_id']


def save_session():
    if 'username' in st.session_state:
        session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
        data = {
            'messages': st.session_state.get('messages', []),
            'prompt_history': st.session_state.get('prompt_history', ""),
            'project_id': st.session_state.get('project_id', None)
        }
        with open(session_file, 'w') as f:
            json.dump(data, f)


if not st.session_state.authenticated:
    # Display logo on login page
    logo_url = "http://nondisk.136138189.xyz:2086/f/Rnsw/biogen-high-resolution-logo-transparent.png"  # Replace with your specified logo URL
    #left_co, cent_co, last_co = st.columns(3)
    ## add some space
    st.markdown(
        """
        <div style="text-align: center;">
            <img src="{logo_url}" alt="Example Image" style="max-width: 25%; height: auto;">
        </div>
        """.format(logo_url=logo_url), unsafe_allow_html=True
    )
    st.markdown('####')
    col1, col2, col3 = st.columns(3)
    #with cent_co:
    #    st.image(logo_url, width=300)
    with col2:
        #st.image(logo_url, width=150)  # Set width to make it slightly smaller
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
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
        cookies.save()
        st.rerun()
    else:
        # Load session if not already loaded
        if 'session_loaded' not in st.session_state:
            load_session()
            st.session_state.session_loaded = True

# Top navigation bar
# st.markdown("""
# <style>
# nav {
#  background-color: #f0f0f0;
#  padding: 10px;
#  text-align: center;
# }
# nav a {
#  margin: 0 10px;
#  text-decoration: none;
#  color: black;
# }
# </style>
# <nav>
# <a href="https://example.com/readme">Readme</a> |
# <a href="https://github.com/example/repo">GitHub</a>
# </nav>
# """, unsafe_allow_html=True)

# Display project logo in sidebar
st.sidebar.image(
    "http://nondisk.136138189.xyz:2086/f/Rnsw/biogen-high-resolution-logo-transparent.png")  # Replace with correct URL

# Add logout and reset buttons in sidebar
st.sidebar.title("Options")
if st.sidebar.button("Logout"):
    session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
    if os.path.exists(session_file):
        os.remove(session_file)
    st.session_state.authenticated = False
    if 'authenticated' in cookies:
        del cookies['authenticated']
    if 'login_time' in cookies:
        del cookies['login_time']
    if 'username' in cookies:
        del cookies['username']
    cookies.save()
    st.session_state.clear()
    st.rerun()

if st.sidebar.button("Reset Session"):
    session_file = os.path.join(persist_dir, f"{st.session_state.username}.json")
    if os.path.exists(session_file):
        os.remove(session_file)
    st.session_state.messages = []
    st.session_state.prompt_history = ""
    st.session_state.project_id = asyncio.run(execute_shell_command_via_api(command=''))
    save_session()  # Optional, since file removed
    st.rerun()


# Check for API_URL and API_KEY
def check_api(reset_project_id=False):
    ## print work dir
    print('work dir:', os.environ.get('WORK_DIR', ''))
    print('api url:', os.environ.get('API_URL', ''))
    print('api key:', os.environ.get('API_KEY', ''))
    try:
        # Assuming execute_shell_command_via_api uses API_URL and API_KEY
        # result = asyncio.run(execute_shell_command_via_api(command=''))
        if ('project_id' not in st.session_state and os.getenv('PROJECT_ID') is None) or reset_project_id:
            result = asyncio.run(execute_shell_command_via_api(command=''))
            st.session_state['project_id'] = os.environ["PROJECT_ID"]
            print('after check api', st.session_state['project_id'])
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
                os.environ['API_URL'] = f"http://{server_ip}:38000"
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
import pty
import select
import fcntl

def api_set(server_ip, username, port, ssh_password, api_key, read_only_dir='', read_write_dir='', work_dir='', allow_raw=''):
    cmd = ['bash', './bioGen/ulits/api_set_warp.sh', server_ip, username, port, ssh_password, api_key, read_only_dir, read_write_dir, work_dir, str(allow_raw)]
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
                        os.environ['API_URL'] = f"http://{server_ip}:38000"
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

def pair_api_set(pair_code):
    pass  # Leave empty as per instructions


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
    tab1, tab2, tab3 = st.tabs(["Manual Setup", "SSH Setup", "Pair Code Setup"])

    with tab1:
        api_url_input = st.text_input("Enter API URL", value=os.environ.get('API_URL', ''))
        api_key_input = st.text_input("Enter API Key", value=os.environ.get('API_KEY', ''), type="password")
        if st.button("Set API Credentials"):
            if api_url_input and api_key_input:
                os.environ['API_URL'] = api_url_input
                os.environ['API_KEY'] = api_key_input
                print(os.environ['API_URL'], os.environ['API_KEY'])
                if check_api(reset_project_id=True):
                    st.success("API credentials set successfully!")
                    st.session_state.api_setup_done = True
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
        api_key = st.text_input("API Key", value=st.session_state.ssh_api_key, type="password")
        if st.button("Generate API Key"):
            st.session_state.ssh_api_key = secrets.token_hex(64)
            st.rerun()
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
                success, output, error_output = api_set(server_ip, username, port, ssh_password, api_key, read_directory, read_write_directory, work_dir)
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
                os.environ['API_URL'] = f"http://{server_ip}:38000"
                os.environ['API_KEY'] = api_key
                print(os.environ['API_URL'], os.environ['API_KEY'])
                if success:
                    if check_api():
                        st.success("API setup successful!")
                        st.session_state.api_setup_done = True
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

# Setup on "chat start" - run once
if "setup_done" not in st.session_state:
    st.session_state.setup_done = True
    st.session_state.input_counter = 0  # Initialize input counter
    st.session_state.processing = False
    st.session_state.output_queue = queue.Queue()
    st.session_state.prompt_queue = queue.Queue()
    st.session_state.response_queue = queue.Queue()
    user_input = create_user_input_func(st.session_state.prompt_queue, st.session_state.response_queue)
    user_action = create_user_action_func(st.session_state.prompt_queue, st.session_state.response_queue)
    user_proxy = UserProxyAgent('user_proxy', input_func=user_input)
    agents_non_proxy = [agent for agent in agents if agent.name != 'user_proxy']
    agents_non_proxy.append(user_proxy)
    selector_team2 = SelectorGroupChat(
        agents_non_proxy,
        model_client=default_model,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=False,
    )
    st.session_state.team = selector_team2
    st.session_state.prompt_history = st.session_state.get('prompt_history', "")
    if 'project_id' not in st.session_state:
        project_id = asyncio.run(execute_shell_command_via_api(command=''))
        st.session_state.project_id = project_id

# Display starters in sidebar
st.sidebar.title("Starters")
for starter in starters:
    if st.sidebar.button(starter["label"]):
        st.session_state.messages.append({"role": "user", "content": starter["message"]})
        save_session()
        st.rerun()

# Initialize messages if not present
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    if message["role"] == "thought":
        with st.expander(f"Thought from {get_avatar(message['source'])} {message['source']}"):
            st.markdown(message["content"])
    else:
        with st.chat_message(message["role"], avatar=get_avatar(message["role"])):
            st.markdown(message["content"])

# Conditional chat input
if not st.session_state.get('processing', False) and "pending_prompt" not in st.session_state:
    message = st.chat_input("Type your message here")
    if message:
        st.session_state.messages.append({"role": "user", "content": message, "processed": False})
        save_session()
        st.info("Initialize the session. If you have loaded memory, this may take up to five minutes.")
        st.rerun()


# Function to process the task in background thread
def process_task(user_message, output_queue, team):
    if 'project_id' not in st.session_state:
        ## init project id
        project_id = execute_shell_command_via_api(command='')
        st.session_state['project_id'] = project_id
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async_gen = team.run_stream(
        task=[TextMessage(content=user_message, source="user")],
        cancellation_token=CancellationToken(),
    )
    current_source = None
    current_content = ""
    while True:
        try:
            msg = loop.run_until_complete(anext(async_gen))
            if msg is None:
                break
            try:
                if msg.source == "user":
                    output_queue.put({'type': 'toast',
                                      'time': 300,
                                      'message': f"Initialize the session. If you have loaded memory, this may take up to five minutes",
                                      'icon': "ℹ️"})
                    continue
                msg_content = msg.content
                if "user_proxy:" in msg_content:
                    continue
                if msg.source == "safety_checker_agent":
                    output_queue.put({'type': 'toast',
                                      'message': f"Start executing command\nView progression at {os.environ.get('API_URL')} with your API key",
                                      'icon': "ℹ️", "time": 999})
                    output_queue.put(
                        {'type': 'toast', 'message': "This page will auto update after command execution is complete.",
                         'icon': "ℹ️", "time": 999})
            except:
                pass
            if isinstance(msg, TaskResult):
                termination_msg = "Task terminated. "
                if msg.stop_reason:
                    termination_msg += msg.stop_reason
                output_queue.put({"role": "system", "content": termination_msg})
                break
            elif isinstance(msg, ThoughtEvent):
                if current_content:
                    output_queue.put({"role": current_source, "content": current_content})
                output_queue.put({"role": "thought", "content": msg.content, "source": msg.source})
                current_source = None
                current_content = ""
            elif isinstance(msg, ModelClientStreamingChunkEvent) or isinstance(msg, TextMessage) or isinstance(msg,
                                                                                                               GroupChatMessage):
                if msg.source != current_source:
                    if current_content:
                        output_queue.put({"role": current_source, "content": current_content})
                    current_source = msg.source
                    current_content = ""
                if isinstance(msg, ModelClientStreamingChunkEvent):
                    current_content += msg.content
                elif isinstance(msg, TextMessage) or isinstance(msg, GroupChatMessage):
                    current_content += msg.content + "\n"
            elif isinstance(msg, ToolCallExecutionEvent) or isinstance(msg, ToolCallRequestEvent):
                if not current_source:
                    current_source = "system"
                try:
                    cmd = msg.content[0].content
                except:
                    cmd = msg.content[0].arguments
                current_content += f"```\n{cmd}\n```\n"
                if isinstance(msg, ToolCallRequestEvent):
                    output_queue.put({'type': 'toast',
                                      'message': f"Start executing command\nView progression at {os.environ.get('API_URL')} with your API key",
                                      'icon': "ℹ️", "time": 999})
                    output_queue.put(
                        {'type': 'toast', 'message': "This page will auto update after command execution is complete.",
                         'icon': "ℹ️", "time": 999})
                    st.info(
                        "This page will auto update after command execution is complete. View progression at {os.environ.get('API_URL')} with your API key. project id: " + str(
                            st.session_state.project_id))
            elif isinstance(msg, UserInputRequestedEvent):
                if current_content:
                    output_queue.put({"role": current_source, "content": current_content})
                    current_content = ""
                st.info(f"User input required: ")

        except StopAsyncIteration:
            break
    if current_content:
        output_queue.put({"role": current_source, "content": current_content})
    output_queue.put({'type': 'done'})


# Process pending user messages
if "messages" in st.session_state and st.session_state.messages:
    last_user_message = next(
        (msg for msg in reversed(st.session_state.messages) if msg["role"] == "user" and not msg.get("processed")),
        None)
    if last_user_message and not st.session_state.get('processing', False):
        user_message = last_user_message["content"]
        last_user_message["processed"] = True
        save_session()
        st.session_state.processing = True
        threading.Thread(target=process_task, args=(user_message, st.session_state.output_queue, st.session_state.team),
                         daemon=True).start()
        st.rerun()

# Polling logic during processing or pending input
if st.session_state.get('processing', False) or "pending_prompt" in st.session_state:
    if "pending_prompt" not in st.session_state:
        st.info("The agent is processing your request. Please wait until further input is required.")
    updated = False

    # Process output queue
    while not st.session_state.output_queue.empty():
        item = st.session_state.output_queue.get()
        if item.get("type") == "done":
            st.session_state.processing = False
            updated = True
        elif item.get("type") == "toast":
            duration_time = 10
            if 'time' in item.keys() and item['time']:
                duration_time = max(30, item['time'])
            st.toast(item["message"], icon=item["icon"], duration=duration_time)
            updated = True
        else:
            st.session_state.messages.append(item)
            updated = True
    if updated:
        save_session()

    # Process prompt queue
    while not st.session_state.prompt_queue.empty():
        prompt_type, prompt = st.session_state.prompt_queue.get()
        st.session_state.pending_prompt_type = prompt_type
        st.session_state.pending_prompt = prompt
        updated = True

    # Handle pending prompt
    if "pending_prompt" in st.session_state:
        st.info(st.session_state.pending_prompt)
        if st.session_state.pending_prompt_type == "input":
            key = f"input_{st.session_state.input_counter}"
            response = st.chat_input("", key=key)
            if response:
                st.session_state.response_queue.put(response)
                st.session_state.input_counter += 1
                del st.session_state.pending_prompt
                del st.session_state.pending_prompt_type
                updated = True
        elif st.session_state.pending_prompt_type == "action":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Approve"):
                    st.session_state.response_queue.put("APPROVE.")
                    del st.session_state.pending_prompt
                    del st.session_state.pending_prompt_type
                    updated = True
            with col2:
                if st.button("Reject"):
                    st.session_state.response_queue.put("REJECT.")
                    del st.session_state.pending_prompt
                    del st.session_state.pending_prompt_type
                    updated = True

    if updated:
        st.rerun()
    else:
        time.sleep(0.1)
        st.rerun()