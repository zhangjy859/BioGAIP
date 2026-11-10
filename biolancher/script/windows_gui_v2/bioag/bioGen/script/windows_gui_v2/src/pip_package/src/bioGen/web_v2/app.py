import sys, os, time, datetime, json, secrets, multiprocessing, signal, re, asyncio, platform
import hashlib
from datetime import timedelta
from multiprocessing import Process, Event
import threading
import requests
import streamlit as st
import random
import logging
from streamlit_cookies_manager import EncryptedCookieManager
from autogen_core import EVENT_LOGGER_NAME

import bioGen.context_summary as bg_summary
from bioGen.web import config as web_config

from bioGen.biogen import *

from storage import get_storage
from utils import LLMUsageTracker, restart_session, get_avatar, force_kill_process, read_uploaded_file
from api_manager import shutdown_server, get_project_status, check_api, api_set2, check_model, pair_api_set
from agent_processor import create_team, process_task

# Globals configuration
logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.setLevel(logging.INFO)
llm_usage = LLMUsageTracker()
logger.handlers = [llm_usage]
version_data = 'v1.3.2'
starters = web_config.starters
max_chat_message_num = os.environ.get('MAX_CHAT_MESSAGE', 200)

work_dir_env = os.getcwd()
persist_dir_env = os.environ.get('PERSIST_DIR', None)
if persist_dir_env is None:
    persist_dir = os.path.join(work_dir_env, 'user_sessions') + f"_{random.randbytes(3).hex()}"
    os.environ['PERSIST_DIR'] = persist_dir
else:
    persist_dir = persist_dir_env

# Initialise data storage backend adapter (Factory handles USE_SQLITE Env Var)
storage = get_storage(persist_dir)


## also save logger to persist_dir for debugging
if os.environ.get('LOG_DIR', None) is None and os.environ.get('SKIP_DIR_OUTPUT', None) is not None:
    log_dir = os.path.join(persist_dir, 'logs')
    os.environ['LOG_DIR'] = log_dir
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(os.path.join(log_dir, 'app.log')), logging.StreamHandler()], format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",)

st.set_page_config(page_title=f"BioGAIP {version_data}", page_icon=":smile:")

cookiers_password = os.environ.get("COOKIE_PASSWORD", None)
if not cookiers_password and not st.session_state.get('cookier_password', None):
    cookiers_password = random.randbytes(64).hex()
    os.environ["COOKIE_PASSWORD"] = cookiers_password
if not st.session_state.get('cookier_password', None):
    st.session_state.cookier_password = os.environ["COOKIE_PASSWORD"]

logger.info(f"Using cookie password: {st.session_state.cookier_password}")
cookies = EncryptedCookieManager(prefix="biogen_", password=st.session_state.cookier_password)
if not cookies.ready(): st.stop()
logger.info(f"Cookies ready: {cookies.ready()}")
#logger.info(f"Cookies ready: {cookies.ready()}")

if "authenticated" not in st.session_state:
    if cookies.ready() and 'authenticated' in cookies and cookies['authenticated'] == 'True':
        try:
            st.session_state.authenticated = True
            st.session_state.login_time = datetime.datetime.fromisoformat(cookies['login_time'])
            st.session_state.username = cookies['username']
        except (ValueError, KeyError):
            del cookies['authenticated']
            if 'login_time' in cookies: del cookies['login_time']
            if 'username' in cookies: del cookies['username']
            cookies.save()
            st.session_state.authenticated = False
    else:
        st.session_state.authenticated = False
        
logger.info("Checked User status")

st.set_page_config(page_title=f"BioGAIP {version_data}", page_icon=":smile:")

if not st.session_state.authenticated:
    logger.info('User authentication')
    logo_url = "https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505"
    st.markdown(f'<div style="text-align: center;"><img src="{logo_url}" alt="Logo" style="max-width: 25%; height: auto;"></div>', unsafe_allow_html=True)
    st.markdown('####')
    col1, col2, col3 = st.columns(3)
    with col2:
        logger.info("Login form")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        with st.expander("Advanced Settings"):
            usrname_id_login = st.text_input("Project ID (optional)", value="")
        if st.button("Login"):
            app_user = os.environ.get('APP_USER')
            salt = os.environ.get('PASSWORD_SALT')
            
            def get_hashed(pwd, s):
                return hashlib.sha256((pwd + s).encode('utf-8')).hexdigest()

            is_valid_login = False

            # Check if APP_USER is a valid file path
            if app_user and os.path.isfile(app_user):
                logger.info('Load User configure')
                try:
                    with open(app_user, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'): continue
                            parts = line.split(':', 1)
                            if len(parts) == 2:
                                file_user, file_pass = parts
                                if file_user == username:
                                    check_pass = get_hashed(password, salt) if salt else password
                                    if check_pass == file_pass:
                                        is_valid_login = True
                                    break
                except Exception as e:
                    st.error(f"Error reading user file: {e}")
            else:
                # Fallback to single inline user:pass config
                logger.info('Load user configure from env')
                expected_username, expected_password = (app_user.split(':', 1) + [''])[:2] if app_user else ("admin", "admin")
                if username == expected_username:
                    check_pass = get_hashed(password, salt) if salt else password
                    if check_pass == expected_password:
                        is_valid_login = True

            if is_valid_login:
                st.session_state.authenticated = True
                st.session_state.login_time = datetime.datetime.now()
                st.session_state.username = username
                cookies['authenticated'] = 'True'
                cookies['login_time'] = st.session_state.login_time.isoformat()
                cookies['username'] = username
                if usrname_id_login:
                    st.session_state.project_id = usrname_id_login
                    cookies['project_id'] = usrname_id_login
                cookies.save()
                storage.load_session(st.session_state.username, st.session_state)
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()
else:
    if (datetime.datetime.now() - st.session_state.login_time) > timedelta(days=3):
        st.session_state.authenticated = False
        if 'authenticated' in cookies: del cookies['authenticated']
        if 'login_time' in cookies: del cookies['login_time']
        if 'username' in cookies: del cookies['username']
        if 'project_id' in cookies: del cookies['project_id']
        cookies.save()
        st.rerun()
    else:
        if 'session_loaded' not in st.session_state:
            if 'project_id' in cookies and 'project_id' not in st.session_state:
                st.session_state.project_id = cookies['project_id']
            storage.load_session(st.session_state.username, st.session_state)
            st.session_state.session_loaded = True
            if st.session_state.get('processing', False) and 'reconnect_warning_shown' not in st.session_state:
                st.warning("You seem to have reconnected while a task was processing. Some recent chat records might have been lost. To avoid this in the future, please keep your browser tab open and active, disable tab sleep in your browser settings, and avoid refreshing the page during long tasks.")
                st.session_state.reconnect_warning_shown = True
                storage.save_session(st.session_state.username, st.session_state)

logger.info('Login page end')

st.sidebar.image("https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505")
st.sidebar.title("Options")
if st.sidebar.button("Logout"):
    for k in ['authenticated', 'login_time', 'username', 'project_id']:
        if k in cookies: del cookies[k]
    cookies.save()
    st.session_state.clear()
    if 'api_process' in st.session_state:
        st.session_state.api_process.kill()
        del st.session_state.api_process
    st.info('Please Manual Refresh web page')

# Extract unique prefix to prevent pollution across different projects of the same user
def get_file_prefix():
    pid = st.session_state.get('project_id', 'default')
    return f"{st.session_state.username}_{pid}"

pid_file = os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")

def check_team_pid_running(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except Exception: return False
    return False

@st.dialog("Reset Session Warning")
def reset_session_confirm():
    st.warning("This will terminate any running tasks and start a new session. All current progress will be lost. Are you sure?")
    if st.button("Confirm Reset"):
        st.info("Reseting session")
        if 'stop_team' in st.session_state:
            try: st.session_state.stop_team.set()
            except AttributeError:
                st.session_state.team_exit_file_set = st.session_state.team_exit_file + '_set'
                with open(st.session_state.team_exit_file_set, 'w') as f: f.write('')
        if 'force_stop' in st.session_state: st.session_state.force_stop.set()
        
        st.session_state.messages.append({"role": "user", "content": 'user stop session'})
        waiting_team_stop = True
        while not os.path.exists(st.session_state.team_exit_file) and waiting_team_stop:
            st.toast("Waitting team stop", icon="ℹ️")
            time.sleep(30)
            waiting_team_stop = False
        if not os.path.exists(st.session_state.team_exit_file):
            st.toast("Stop team fail, team is still running after wait 30s, force stoping...", icon="ℹ️")
            force_kill_process(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid"), logger)
        else:
            os.remove(st.session_state.team_exit_file)      
        if 'team' in st.session_state: del st.session_state.team
        st.session_state.processing = False
        st.session_state.show_refresh_botton = True
        
        if 'project_id' in st.session_state:
            st.info("Reseting project")
            project_status = get_project_status(st.session_state.project_id, API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
            if isinstance(project_status, dict) and project_status.get('status') == 'running':
                task_id = project_status.get('current_task_id')
                if task_id:
                    try: requests.post(f"{os.environ.get('API_URL')}/tasks/{task_id}/kill", headers={"x-api-key": os.environ.get('API_KEY')})
                    except Exception: pass
        
        st.session_state.messages = []
        st.session_state.prompt_history = ""
        storage.delete_session(st.session_state.username, st.session_state)
        asyncio.run(execute_shell_command_via_api(command=''))
        st.session_state.project_id = os.environ["PROJECT_ID"]
        
        if remote_tool_loaded:
            try: _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ['PROJECT_ID'], api_base_url=os.environ['API_URL'], api_key=os.environ['API_KEY'])
            except Exception: pass

        st.session_state.log_file = os.path.join(persist_dir, f"{get_file_prefix()}_log.ndjson")
        st.session_state.input_file = os.path.join(persist_dir, f"{get_file_prefix()}_input.txt")
        if not os.path.exists(st.session_state.log_file): open(st.session_state.log_file, 'w').close()
        if not os.path.exists(st.session_state.input_file): open(st.session_state.input_file, 'w').close()
        
        for k in ['pending_prompt', 'pending_prompt_type', 'input_prompt']:
            if k in st.session_state: del st.session_state[k]
            
        storage.save_session(st.session_state.username, st.session_state)
        st.session_state.authenticated = False
        for k in ['authenticated', 'login_time', 'username', 'project_id']:
            if k in cookies: del cookies[k]
        cookies.save()
        st.session_state.clear()
        if 'api_process' in st.session_state:
            st.session_state.api_process.kill()
            del st.session_state.api_process
        st.info('Please Manual Refresh web page')
        _ = restart_session()
        st.rerun()

if st.sidebar.button("Reset Session"):
    reset_session_confirm()
    st.components.v1.html("<script>window.location.reload(true);</script>", height=0, width=0)

if "api_setup_done" not in st.session_state:
    api_url = os.environ.get('API_URL')
    api_key = os.environ.get('API_KEY')
    if not api_url or not api_key: st.session_state.api_setup_done = False
    else: st.session_state.api_setup_done = check_api(st.session_state, remote_tool_loaded, logger)

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
                ## for firefox compatibility
                if usrname_id_login is None:
                    usrname_id_login = ''
                logger.info(f"API credentials set: URL={api_url_input}, Key={'*' * len(api_key_input)}")
                logger.info(f"Project ID set: {usrname_id_login}")
                reset_project_id = usrname_id_login != '' and usrname_id_login
                if reset_project_id:
                    st.session_state.project_id = usrname_id_login
                    os.environ['PROJECT_ID'] = st.session_state.project_id
                if check_api(st.session_state, remote_tool_loaded, logger, reset_project_id=reset_project_id):
                    st.success("API credentials set successfully!")
                    st.session_state.api_setup_done = True
                    if usrname_id_login != '' and usrname_id_login != st.session_state.get('project_id', ''):
                        st.session_state.project_id = usrname_id_login
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
        work_dir = st.text_input("Working Directory (Optional), bioWorker will store cache files here")
        temp_dir = st.text_input("Temporary Directory (Optional), bioWorker will store temporary files here")
        if "ssh_api_key" not in st.session_state:
            st.session_state.ssh_api_key = ""
        st.info('Please note down the generated API key, as it will not be shown again. You will need it to access the API at other place.')
        api_key = st.text_input("bioWorker API Key", value=st.session_state.ssh_api_key, type="password")
        if st.button("Generate API Key"):
            st.session_state.ssh_api_key = secrets.token_hex(64)
            st.rerun()
        with st.expander("Advanced Settings"):
            use_sandbox = st.selectbox('Sandbox Mode', ['Disabled', 'bubblewrap', 'landlock'], index=0)
            st.info("Sandboxing allowed restricts bioWorker's access to the system, enhancing security with docker or other containerization technology. However, it may cause issues and unsafe on some systems.")
            bioworker_port = st.text_input("Bioworker Port", value="38000")
            max_task = st.number_input("Maximum number of tasks for bioWorker of project", min_value=1, max_value=100, value=1, step=1)
            web_admin_panel = st.checkbox("Enable web admin panel for bioWorker", value=False)
        
        if use_sandbox == 'bubblewrap':
            use_sandbox_type = 'bubblewrap'
        elif use_sandbox == 'landlock':
            use_sandbox_type = 'landlock'
        elif use_sandbox == 'Disabled':
            use_sandbox_type = None
        else:
            raise ValueError("Invalid sandbox mode selected.")
            
        if not read_directory: read_directory = ''
        if not read_write_directory: read_write_directory = ''
        if not work_dir: work_dir = ''
        if not temp_dir: temp_dir = ''
        
        if st.button("Initialize via SSH"):
            if server_ip and username and port and ssh_password and api_key:
                st.info('Initializing BioWorker at your server with SSH, thats may take 5-10 minutes, BioWorker will remain running in the background. If you wish to stop it, please do so through the BioAG panel, or execute " docker stop $(docker ps -q --filter "name=^bioworker_") " in the server.')
                success, output, error_output = api_set2(server_ip, username, port, ssh_password, api_key, read_directory, read_write_directory, work_dir, bioworker_port=bioworker_port, use_sandbox_type=use_sandbox_type, temp_dir=temp_dir, max_task=max_task, web_admin=web_admin_panel)
                if not success:
                    st.error("Setup failed. Please check the error messages.")
                    if error_output: st.text_area("Error Output", error_output, height=200)
                    if output: st.text_area("Output", output, height=200)
                    if 'api_process' in st.session_state:
                        st.session_state.api_process.kill()
                        del st.session_state.api_process
                    st.stop()
                os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                os.environ['API_KEY'] = api_key
                if success:
                    if check_api(st.session_state, remote_tool_loaded, logger):
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
        st.error("This mode is not open for user current now because of safety concerns.")
        pair_code = st.text_input("Pair Code")
        if st.button("Initialize via Pair Code"):
            pair_api_set(pair_code)
            if check_api(st.session_state, remote_tool_loaded, logger):
                st.success("API setup successful!")
                st.session_state.api_setup_done = True
                st.rerun()
            else:
                st.error("Setup failed.")
    st.stop()

if "setup_done" not in st.session_state:
    st.session_state.setup_done = True
    if 'input_counter' not in st.session_state:
        st.session_state.input_counter = 0 
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'project_id' not in st.session_state:
        st.session_state.project_id = asyncio.run(execute_shell_command_via_api(command=''))
        os.environ['PROJECT_ID'] = st.session_state.project_id
        if remote_tool_loaded:
            try: _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ['PROJECT_ID'], api_base_url=os.environ['API_URL'], api_key=os.environ['API_KEY'])
            except Exception: pass
    
    st.session_state.log_file = os.path.join(persist_dir, f"{get_file_prefix()}_log.ndjson")
    st.session_state.input_file = os.path.join(persist_dir, f"{get_file_prefix()}_input.txt")
    if not os.path.exists(st.session_state.log_file): open(st.session_state.log_file, 'w').close()
    if not os.path.exists(st.session_state.input_file): open(st.session_state.input_file, 'w').close()
    st.session_state.agent_status_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
    st.session_state.prompt_history = st.session_state.get('prompt_history', "")

st.sidebar.title("Examples")
for starter in starters:
    if st.sidebar.button(starter["label"]):
        st.session_state.messages.append({"role": "user", "content": starter["message"]})
        storage.save_session(st.session_state.username, st.session_state)
        st.rerun()

@st.dialog("Kill Task Confirmation")
def kill_task_confirm(task_id):
    if task_id is None and task_id: return
    st.warning("This will terminate the running task. Are you sure?")
    st.info("If you cant stop task here, please manager task at bioWorker panel")
    message = st.text_input("Optional message about why you want to stop task (can be empty):")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel"): st.rerun()
    with col2:
        if st.button("Confirm"):
            try:
                st.info(f"Trying to stop task {task_id}")
                requests.post(f"{os.environ['API_URL']}/tasks/{task_id}/kill", json={"message": message}, headers={"x-api-key": os.environ['API_KEY']}).raise_for_status()
                st.success("Kill signal sent.")
                time.sleep(2)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to kill task: {str(e)}")

st.sidebar.title("bioWorker status")
if os.environ.get('API_URL', '') != '' and os.environ.get('API_KEY', '') != '':
    st.sidebar.markdown(f"**Project ID:** {st.session_state['project_id']}")
    project_status = get_project_status(st.session_state['project_id'], API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
    bioworker_placeholder_status = st.sidebar.empty()
    if isinstance(project_status, dict):
        status = project_status.get('status', 'unknown')
        current_command = project_status.get('current_command', 'N/A')
        bioworker_placeholder_status.info(f"**Status:** {status.capitalize()}\n\n**Current Command:**\n\n ```\n\n{current_command} \n\n```")
        if status == 'running':
            task_id = project_status.get('current_task_id')
            st.session_state.current_task_id = task_id
            if task_id and st.sidebar.button("Kill Task"):
                st.session_state.show_kill_dialog = True
    if st.sidebar.button("Stop bioWorker API Server"):
        try: shutdown_server(host=os.environ.get('API_URL'), api_key=os.environ.get('API_KEY'))
        except Exception: pass
        if 'api_process' in st.session_state:
            st.session_state.api_process.kill()
            del st.session_state.api_process
        os.environ['API_URL'], os.environ['API_KEY'] = '', ''
        st.session_state.api_setup_done = False
        st.sidebar.success("bioWorker API server stopped.")
        st.rerun()
    st.sidebar.markdown(f"[Go to bioWorker Control Panel]({os.environ.get('API_URL')})")

if st.session_state.get('show_kill_dialog', False):
    kill_task_confirm(st.session_state.get('current_task_id', False))
    time.sleep(9)
    st.session_state.show_kill_dialog = False

st.sidebar.markdown(f"<div style='position: fixed; bottom: 10px; font-size: 10px; color: grey;'>bioGen Version: {version_data}</div>", unsafe_allow_html=True)

if "messages" not in st.session_state: st.session_state.messages = []
if "message_processed_front_ui_uuid" not in st.session_state: st.session_state.message_processed_front_ui_uuid = []

for message in st.session_state.messages:
    message_uuid = message.get('message_uuid', None)
    if message["role"] != "user_proxy" and message["content"].startswith("@user_proxy:") and message["content"].startswith("user_proxy:"): continue
    if message["role"] == "thought":
        with st.expander(f"Thought from {get_avatar(message['source'])} {message['source']}"):
            st.markdown(message["content"])
    else:
        with st.chat_message(message["role"], avatar=get_avatar(message["role"])):
            # OPTIMIZATION: Cache regex processing into the message dict to avoid expensive CPU operations on every UI redraw
            if "cleaned_content" not in message or "file_blocks" not in message:
                content = message["content"]
                message["file_blocks"] = re.findall(r'<uploaded_file name="(.*?)" ext="(.*?)"\>(.*?)</uploaded_file>', content, re.DOTALL)
                message["cleaned_content"] = re.sub(r'<uploaded_file name=".*?" ext=".*?"\>(.*?)</uploaded_file>', '', content, flags=re.DOTALL)
            
            st.markdown(message["cleaned_content"].strip())
            for name, ext, file_content in message["file_blocks"]:
                with st.expander(f"Uploaded file: {name}"):
                    st.code(file_content.strip(), language=ext.lower() if ext.lower() in ['python', 'json', 'html', 'md', 'txt'] else None)
    if message_uuid: st.session_state.message_processed_front_ui_uuid.append(message_uuid)

st.markdown('''
<style>
[data-testid="stFileUploaderDropzone"] { width: 2.2rem; height: 2.2rem; background: transparent !important; border: none !important; padding: 0 !important; margin: 0 !important; min-width: unset !important; }
[data-testid="stFileUploaderDropzone"] div, [data-testid="stFileUploaderDropzone"] small, [data-testid="stFileUploaderDropzone"] p, [data-testid="stFileUploaderDropzone"] ul { display: none !important; }
[data-testid="stFileUploaderDropzone"] button { height: 2.2rem; min-width: 2.2rem; width: 2.2rem; padding: 0; border-radius: 50%; text-indent: -9999px; overflow: hidden; position: relative; }
[data-testid="stFileUploaderDropzone"] button > span { display: none !important; }
[data-testid="stFileUploaderDropzone"] button:after { content: "📎"; font-size: 1.2rem; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-indent: 0; }
div.element-container button.row-widget.stButton { height: 2.2rem; min-width: 2.2rem; width: 2.2rem; padding: 0; border-radius: 50%; font-size: 1.2rem; display: flex; align-items: center; justify-content: center; margin-left: auto; background-color: transparent !important; border: none !important; }
</style>
''', unsafe_allow_html=True)

if 'last_uploaded_files' not in st.session_state: st.session_state.last_uploaded_files = set()
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
st.session_state.init_messaged = False

placeholder_text = "Type your response here" if st.session_state.get('waiting_for_user_input', False) else "Type your message here"
if st.session_state.get('processing', False): placeholder_text = "Please stop team firstly and type your response here if you need input"

user_prompt_json = os.path.join(persist_dir, f"{get_file_prefix()}_input.ujson")

with st._bottom:
    col1, col2, col3, col4 = st.columns([1, 20, 1, 1])
    with col1:
        uploaded_files = st.file_uploader(
            "Upload files", label_visibility="collapsed", key=f"chat_file_uploader_{st.session_state.uploader_key}", accept_multiple_files=True,
            type=['txt', 'md', 'html', 'pdf', 'htm', 'py', 'js', 'sh', 'docx', 'xlsx', 'pptx', 'java', 'c', 'cpp', 'h', 'rb', 'pl', 'php', 'go', 'rs', 'kt', 'swift', 'r', 'm', 'lua', 'cs', 'ts', 'scala', 'groovy', 'perl', 'bat', 'cmd', 'ps1', 'pm', 'vb', 'f', 'f90', 'jl', 'hs', 'Rmd', 'ipynb']
        )
    with col2:
        message = st.chat_input(placeholder_text)
        if message:
            if 'automatic_start' in st.session_state: st.session_state.automatic_start = True
            storage.safe_append(user_prompt_json, {'role': 'user', 'message': message}, username=st.session_state.username)
            
    with col3:
        if st.session_state.get('processing', False):
            if st.button("🛑"):
                project_status = get_project_status(st.session_state.project_id, os.environ['API_URL'], os.environ['API_KEY'])
                if isinstance(project_status, dict) and project_status.get('status') == 'running':
                    st.toast("Please manually stop the ongoing task in the bioWorker panel.", icon="⚠️")
                else:
                    st.session_state.prompt_history = "\n\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
                    storage.save_session(st.session_state.username, st.session_state)
                    team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
                    st.session_state.team_exit_file = team_exit_file 
                    try: st.session_state.stop_team.set()
                    except AttributeError:
                        st.session_state.team_exit_file_set = team_exit_file + '_set'
                        with open(st.session_state.team_exit_file_set, 'w') as f: f.write('')
                    waiting_team_stop = True
                    while not os.path.exists(st.session_state.team_exit_file) and waiting_team_stop:
                        st.toast("Waitting team stop", icon="ℹ️")
                        time.sleep(30)
                        waiting_team_stop = False
                    if not os.path.exists(st.session_state.team_exit_file):
                        st.toast("Stop team fail, team is still running after wait 30s, force stoping...", icon="ℹ️")
                        force_kill_process(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid"), logger)
                    else:
                        os.remove(st.session_state.team_exit_file)      
                    if 'team' in st.session_state: del st.session_state.team
                    st.session_state.processing = False
                    st.session_state.show_refresh_botton = True
                    st.toast("Team stopped. You can resume by providing new input.", icon="ℹ️")

    with col4:
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
                    st.session_state.run_summary, st.session_state.show_refresh_dialog = True, False
                    st.session_state.clear_session_content = clear_history
                    st.session_state.automatic_start = automatic_start
                    st.rerun()

        if st.session_state.get('processing', False) or st.session_state.get('show_refresh_botton', False):
            if st.button("🔃", key="refresh_button"):
                project_status = get_project_status(st.session_state.project_id, API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
                if isinstance(project_status, dict) and project_status.get('status') == 'running':
                    st.toast("Please manually stop the ongoing task in the bioWorker panel, and retry.", icon="⚠️")
                    st.rerun()
                st.session_state.run_summary = False
                st.session_state.show_refresh_dialog = True
                st.session_state.user_confirmed_summary = False
                st.session_state.user_required_summary = True
                st.rerun()

            if st.session_state.get('show_refresh_dialog', False):
                st.session_state.team_summary_file = os.path.join(persist_dir, f"{get_file_prefix()}.summary_team")
                st.session_state.team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
                _refresh_session_confirm()

            if st.session_state.get('run_summary', False):
                st.toast('Please wait up to one min')
                with open(st.session_state.team_exit_file + '_set', 'w') as f: f.write('') 
                with open(st.session_state.team_summary_file, 'w') as f: f.write('')
                time.sleep(10)
                if not os.path.exists(st.session_state.team_exit_file) and check_team_pid_running(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")):
                    st.toast('Fail to refresh session, force restart')
                    force_kill_process(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid"), logger)
                else:
                    st.toast('restarting session')
                st.session_state.run_summary = False
                st.session_state.show_refresh_dialog = False
                @st.dialog("Hint")
                def _refresh_page_hint():
                    ## show a markdown and ok button
                    st.markdown("Please refresh the page to continue.")
                    if st.button("OK"):
                        return
                #_refresh_page_hint()
                st.rerun()

if message is not None:
    full_message = message.strip() if message else ""
    file_contents = []
    if uploaded_files:
        new_files = [f for f in uploaded_files if f.name not in st.session_state.last_uploaded_files]
        for f in new_files:
            content = read_uploaded_file(f)
            if content: file_contents.append(content)
            st.session_state.last_uploaded_files.add(f.name)
        if new_files:
            st.toast("For better file handling, please refer to our documentation on using RAG instead of direct uploads.", icon="ℹ️", duration=19)
    if file_contents: full_message += "\n\n" + "".join(file_contents) if full_message else "".join(file_contents)
    if full_message:
        if st.session_state.get('waiting_for_user_input', False):
            with open(st.session_state.input_file, 'w') as f: f.write(full_message)
            st.session_state.messages.append({"role": "user", "content": full_message})
            del st.session_state.waiting_for_user_input
        else:
            st.session_state.messages.append({"role": "user", "content": full_message, "processed": False})
            if st.session_state.get('init_processing', False): 
                st.session_state.processing = False
                st.session_state.init_processing = False
            if not st.session_state.init_messaged: 
                st.info("Initialize the session. If you have loaded memory, this may take up to five minutes.")
                st.session_state.init_messaged = True
        storage.save_session(st.session_state.username, st.session_state)
        st.session_state.uploader_key += 1
        st.rerun()

team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
team_summary_file = os.path.join(persist_dir, f"{get_file_prefix()}.summary_team")
pid_file = os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")
team_summary = os.path.exists(team_summary_file)

if "messages" in st.session_state and st.session_state.messages:
    last_user_message = next((msg for msg in reversed(st.session_state.messages) if msg["role"] == "user" and not msg.get("processed")), None)
    
    if (last_user_message is not None or team_summary) and (not st.session_state.get('processing', False) or os.path.exists(team_exit_file) or not check_team_pid_running(pid_file)):
        user_message = last_user_message["content"] if last_user_message else "Please continue tasks"
        if last_user_message: last_user_message["processed"] = True
        storage.save_session(st.session_state.username, st.session_state)
        
        st.session_state.processing = True
        st.session_state.processing_start_time = time.time()
        st.session_state.last_save_time = time.time()
        st.components.v1.html("<script>setInterval(() => { console.log('Keeping connection alive'); }, 5000); setInterval(() => { location.reload(); }, 600000); </script>", height=0)
        
        st.session_state.stop_team = multiprocessing.Event()
        st.session_state.force_stop = multiprocessing.Event()
        st.session_state.agent_status_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
        st.session_state.team_exit_file = team_exit_file 
        st.session_state.pid_file = pid_file
        
        if os.path.exists(team_exit_file) or not check_team_pid_running(pid_file):
            if 'team' in st.session_state: del st.session_state.team
            try: os.remove(team_exit_file)
            except Exception: pass
            
        st.session_state.team_summary_file = team_summary_file
        st.session_state.max_content = sys_config.get('max_content', 1000)
        st.session_state.max_summary_content = sys_config.get('max_summary_content', 10000)
        if os.path.exists(team_summary_file):
            os.remove(team_summary_file)
            team_summary = True
        else:
            team_summary = False

        if os.path.exists(team_summary_file + '_no_user_confirm'):
            os.remove(team_summary_file + '_no_user_confirm')

        if 'team' not in st.session_state:
            st.session_state.team = create_team(storage, persist_dir, file=st.session_state.agent_status_file, team_summary=team_summary, logger=logger)
            st.session_state.load_history = not team_summary and not st.session_state.get('finish_summary', False)
            if st.session_state.load_history: st.session_state.finish_summary = False
            
            if team_summary:
                ag_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
                if os.path.exists(ag_file): os.remove(ag_file)
                
                user_prompt_history = storage.get_user_prompt_history(st.session_state.username, file_path=user_prompt_json)
                session_file_for_summary = storage.export_session_to_json(st.session_state.username, st.session_state)
                
                content_summary = bg_summary.run_summary(session_file_for_summary, content_summary_model, st.session_state.max_summary_content, user_prompt_history)
                st.session_state.chat_summary_message = f"==============User Orginal task============\n{str(user_prompt_history)}\nCurrent Processing Summary:\n{content_summary}\n"
                
                @st.dialog("Edit Chat Summary", width="large")
                def edit_chat_summary():
                    edited = st.text_area("Edit the chat summary:", value=st.session_state.get("chat_summary_message", ""), height=300, key="edit_summary_textarea")
                    if st.button("Confirm", type="primary", use_container_width=True):
                        st.session_state.chat_summary_message = edited
                        st.session_state.user_confirmed_summary = True
                        st.rerun()
                
                if not st.session_state.get("user_confirmed_summary", False) and st.session_state.get("user_required_summary", False):
                    st.session_state.user_confirmed_summary = True
                if st.session_state.get("user_confirmed_summary", False) or not st.session_state.get("user_required_summary", False):
                    if "user_required_summary" in st.session_state: del st.session_state.user_required_summary
                    chat_content = {"role": "system", "content": f"Previous conversation content summarized as: \n```{st.session_state.get('chat_summary_message')}```\n. Continue to work on the task."}
                    with open(st.session_state.log_file, 'a') as f: storage.json_safedump(chat_content, f)
                    st.session_state.messages.append(chat_content)
                    st.toast("Chat summary applied. Continuing with the task. Please Wait more times for reload session", icon="✅", duration=60)
                    st.session_state.finish_summary, st.session_state.processing = True, True
                ## add to user_message
                user_message = user_message + f"==============User Orginal task============\n{str(user_prompt_history)}\nCurrent Processing Summary:\n{content_summary}\n\nPlease continue to work on the task."
                st.session_state.user_confirmed_summary = False

        if not team_summary or st.session_state.get('finish_summary', False):
            st.session_state.stop_team = multiprocessing.Event()
            st.session_state.force_stop = multiprocessing.Event()
            for file in [team_exit_file, team_exit_file + '_set', st.session_state.agent_status_file, pid_file, st.session_state.team_summary_file, team_summary_file + '_no_user_confirm']:
                if os.path.exists(file): os.remove(file)
            if os.path.exists(st.session_state.log_file): open(st.session_state.log_file, 'w').close()
            
            if st.session_state.get('clear_session_content', False):
                storage.backup_session(st.session_state.username, st.session_state)
                st.session_state.clear_session_content = False
                st.session_state.messages = []
                if st.session_state.get("chat_summary_message", ""):
                    st.session_state.messages.append({"role": "system", "content": f"Previous conversation content summarized as: \n```{st.session_state.get('chat_summary_message', '')}```\n. Continue to work on the task."})
                    st.info('Previous session content cleared. Please refresh web page to see the changes.')
                storage.save_session(st.session_state.username, st.session_state)
            
            if st.session_state.get('automatic_start', True): 
                sucessfulExecutate_reward = sys_config.get('sucessfulExecutate_reward', 10)
                if platform.system().lower() != 'windows':
                    process_p = Process(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, os.getpid()), daemon=True)
                    process_p.start()
                    with open(pid_file, 'w') as f: f.write(str(process_p.pid))
                else:
                    process_p = threading.Thread(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, None), daemon=True)
                    process_p.start()
                    with open(pid_file, 'w') as f: f.write(str(os.getpid()))
                st.toast('Team starting', icon="✅", duration=60)
                if 'init_processing' in st.session_state: st.session_state.init_processing = False
            else:
                st.toast('Automatic start disabled. Please Copy summary message, edit if need, paste in input box, submit message to resume session.', icon="ℹ️", duration=9000)
            st.rerun()

if st.session_state.get('processing', False):
    waiting_placeholder = st.empty()
    with waiting_placeholder.container(): st.info("The agent is processing your request. Please wait until further input is required.")
    updated = False
    if 'message_processed_uuid' not in st.session_state.keys(): st.session_state.message_processed_uuid = []

    if os.path.exists(st.session_state.log_file):
        with open(st.session_state.log_file, 'r') as f: lines = f.readlines()
        if lines:
            for line in lines:
                try:
                    item = json.loads(line)
                    message_uuid = item.get('message_uuid', None)
                    if message_uuid and message_uuid in st.session_state.message_processed_uuid: continue
                    else: st.session_state.message_processed_uuid.append(message_uuid)
                    
                    if item.get('type') == 'prompt' and item['prompt_type'] == 'input':
                        content = item['content'].replace("@user_proxy:", "").strip()
                        if not st.session_state.messages or st.session_state.messages[-1].get('content') != content:
                            st.session_state.messages.append({"role": "user_proxy", "content": content})
                        st.session_state.waiting_for_user_input, updated = True, True
                    elif item.get('type') == 'toast':
                        st.toast(item["message"], icon=item.get('icon'), duration=max(30, item.get('time', 10)))
                        updated = True
                    elif item.get('type') == 'stream_update':
                        if st.session_state.messages and st.session_state.messages[-1].get('role') == item['source']:
                            st.session_state.messages[-1]['content'] = item['content']
                            # SECURITY/CACHE INVALIDATION: Clear regex cache when streamed content modifies the message 
                            st.session_state.messages[-1].pop('cleaned_content', None)
                            st.session_state.messages[-1].pop('file_blocks', None)
                        else: st.session_state.messages.append({"role": item['source'], "content": item['content'], "source": item['source']})
                        updated = True
                    elif item.get('type') == 'done':
                        if 'stop_team' in st.session_state: st.session_state.stop_team.clear()
                        updated = True
                    elif item.get('type') == 'message':
                        if not st.session_state.messages or not (st.session_state.messages[-1].get('role') == item['role'] and st.session_state.messages[-1].get('content') == item['content']):
                            st.session_state.messages.append({"role": item['role'], "content": item['content'], "source": item.get('source')})
                        updated = True
                    if message_uuid and item.get('type') == 'message':
                        st.session_state.messages[-1] = {**st.session_state.messages[-1], "message_uuid": message_uuid, "message_processed": False}
                except json.JSONDecodeError: pass
            open(st.session_state.log_file, 'w').close()
            updated = True

    try:
        project_status = get_project_status(st.session_state['project_id'], API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
        if isinstance(project_status, dict):
            bioworker_placeholder_status.info(f"**Status:** {project_status.get('status', 'unknown').capitalize()}\n\n**Current Command:**\n\n ```\n\n{project_status.get('current_command', 'N/A')} \n\n ```")
    except Exception: pass

    if updated:
        storage.save_session(st.session_state.username, st.session_state)
        st.session_state.last_save_time = time.time()
        st.rerun()
    else:
        for _ in range(4):
            current_log_size = os.path.getsize(st.session_state.log_file) if os.path.exists(st.session_state.log_file) else 0
            if current_log_size > 0:
                break # New logs detected, break early to process and rerun
            
            time.sleep(0.5)
            
            elapsed = time.time() - st.session_state.get('processing_start_time', time.time())
            with waiting_placeholder.container():
                if elapsed - st.session_state.get('last_st_time', 0) > 5:
                    st.session_state.last_st_time = elapsed
                    st.info(f"Execution time elapsed: {int(elapsed)} seconds")

        if time.time() - st.session_state.get('last_save_time', 0) > 600:
            storage.save_session(st.session_state.username, st.session_state)
            st.session_state.last_save_time = time.time()
            
        st.rerun()