import sys, os, time, datetime, json, secrets, multiprocessing, signal, re, asyncio, platform
import hashlib, zipfile, io
from datetime import timedelta
from multiprocessing import Process, Event
import threading
import requests
import streamlit as st
import streamlit.components.v1 as components
import random
import logging
from streamlit_cookies_manager import EncryptedCookieManager
from autogen_core import EVENT_LOGGER_NAME

import bioGen.context_summary as bg_summary
from bioGen.web import config as web_config
from bioGen.biogen import *
from bioGen.web_v2.storage import get_storage
from bioGen.web_v2.utils import LLMUsageTracker, restart_session, get_avatar, force_kill_process, read_uploaded_file
from bioGen.web_v2.api_manager import shutdown_server, get_project_status, check_api, api_set2, check_model, pair_api_set
from bioGen.web_v2.agent_processor import create_team, process_task

logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.setLevel(logging.INFO)
llm_usage = LLMUsageTracker()
logger.handlers = [llm_usage]
version_data = 'v1.3.4'

starters = list(getattr(web_config, 'starters', []))
starters.append({
    "label": "Genomic Phasing",
    "message": "Perform genomic phasing analysis to resolve haplotype blocks from the provided variant data."
})

max_chat_message_num = os.environ.get('MAX_CHAT_MESSAGE', 200)

work_dir_env = os.getcwd()
persist_dir_env = os.environ.get('PERSIST_DIR', None)
if persist_dir_env is None:
    persist_dir = os.path.join(work_dir_env, 'user_sessions') + f"_{random.randbytes(3).hex()}"
    os.environ['PERSIST_DIR'] = persist_dir
else:
    persist_dir = persist_dir_env

storage = get_storage(persist_dir)

if os.environ.get('REDIRECT_LOGGER_TO_PERSIST_DIR', '').lower() in ['1', 'true', 'yes']:
    try:
        os.makedirs(persist_dir, exist_ok=True)
        log_file_path = os.path.join(persist_dir, 'redirected_app.log')
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"))
        logger.addHandler(file_handler)
    except Exception: pass

if os.environ.get('LOG_DIR', None) is None and os.environ.get('SKIP_DIR_OUTPUT', None) is not None:
    log_dir = os.path.join(persist_dir, 'logs')
    os.environ['LOG_DIR'] = log_dir
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(os.path.join(log_dir, 'app.log')), logging.StreamHandler()], format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s")

st.set_page_config(page_title=f"BioGAIP {version_data}", page_icon="🧬", layout="centered")

if st.session_state.get('trigger_browser_reload', False):
    st.session_state.trigger_browser_reload = False
    try:
        if 'username' in st.session_state:
            storage.save_session(st.session_state.username, st.session_state)
    except Exception: pass
    st.markdown("""
        <div style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background-color: rgba(255, 255, 255, 0.98); z-index: 999999; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; backdrop-filter: blur(10px);">
            <div style="font-size: 72px; margin-bottom: 24px;">🧹</div>
            <h2 style="color: #0f172a; font-family: system-ui, sans-serif; margin-bottom: 16px; font-weight: 800;">Workspace Cleared</h2>
            <p style="color: #475569; font-size: 18px; margin-bottom: 32px; max-width: 500px; line-height: 1.6;">To guarantee all residual data, cached states, and UI components are completely purged, a manual browser refresh is required.</p>
            <div style="padding: 14px 28px; background: linear-gradient(135deg, #3b82f6, #2563eb); color: white; border-radius: 12px; font-weight: 600; font-family: system-ui, sans-serif; font-size: 18px; box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.4), 0 8px 10px -6px rgba(59, 130, 246, 0.1);">
                Please press F5 or Cmd/Ctrl + R
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.stop()

st.markdown("""
    <style>
    [data-testid="stHeader"], .stDeployButton, #MainMenu { display: none !important; }
    
    #splash-screen {
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background-color: #ffffff;
        z-index: 999999; display: flex; flex-direction: column; justify-content: center; align-items: center;
        animation: fadeOut 0.5s ease-in-out forwards; animation-delay: 1.0s; pointer-events: none;
    }
    @keyframes fadeOut { 0% { opacity: 1; } 100% { opacity: 0; visibility: hidden; } }
    .loader-ring {
        border: 4px solid #f1f5f9; border-top: 4px solid #3b82f6; border-radius: 50%;
        width: 48px; height: 48px; animation: spin 0.8s linear infinite;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    
    [data-testid="stBottom"] > div > div > div { display: flex !important; flex-direction: row !important; align-items: flex-end !important; justify-content: center !important; padding-bottom: 24px !important; }
    [data-testid="stBottom"] > div > div > div > div:has([data-testid="stChatInput"]) { order: 1 !important; flex: 1 1 auto !important; width: 100% !important; margin: 0 !important; padding: 0 !important; }
    [data-testid="stChatInput"] { width: 100% !important; margin: 0 !important; padding: 0 !important; border-radius: 12px !important; border: 1px solid rgba(128, 128, 128, 0.25) !important; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important; background-color: transparent !important; }
    [data-testid="stChatInput"] > div, [data-testid="stChatInput"] div[data-baseweb="base-input"], [data-testid="stChatInput"] div[data-baseweb="input"], [data-testid="stChatInput"] div[data-baseweb="textarea"] { border-radius: 12px !important; background: transparent !important; border: none !important; box-shadow: none !important; margin: 0 !important; }
    [data-testid="stChatInputSubmitButton"] { position: absolute !important; right: 0.6rem !important; bottom: 0.6rem !important; }
    [data-testid="stBottom"] > div > div > div > div:has(.st-key-chat_controls) { order: 2 !important; flex: 0 0 auto !important; width: auto !important; padding: 0 !important; margin: 0 0 4px 12px !important; }
    .st-key-chat_controls { display: flex !important; align-items: flex-end !important; margin: 0 !important; padding: 0 !important; background: transparent !important; }
    .st-key-chat_controls [data-testid="stHorizontalBlock"] { gap: 12px !important; align-items: flex-end !important; margin: 0 !important; padding: 0 !important; }
    .st-key-chat_controls [data-testid="column"] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; padding: 0 !important; margin: 0 !important; }
    .st-key-chat_controls button { border-radius: 50% !important; width: 44px !important; height: 44px !important; min-height: 44px !important; min-width: 44px !important; padding: 0 !important; margin: 0 !important; background: #ffffff !important; border: 1px solid rgba(128, 128, 128, 0.25) !important; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08) !important; display: flex !important; justify-content: center !important; align-items: center !important; font-size: 1.25rem !important; transition: all 0.2s ease-in-out !important; color: #475569 !important; line-height: 1 !important; }
    .st-key-chat_controls button:hover { background-color: #f8fafc !important; transform: translateY(-2px) !important; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12) !important; color: #0f172a !important; border-color: #cbd5e1 !important; }
    .st-key-chat_controls button:active { transform: translateY(0) !important; background-color: #f1f5f9 !important; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05) !important; }
    </style>
    <div id="splash-screen"><div class="loader-ring"></div><h3 style="color:#1e293b; margin-top:24px; font-family:system-ui, sans-serif; font-weight:500;">Initializing BioGAIP...</h3></div>
""", unsafe_allow_html=True)

cookiers_password = os.environ.get("COOKIE_PASSWORD", None)
if not cookiers_password and not st.session_state.get('cookier_password', None):
    cookiers_password = random.randbytes(64).hex()
    os.environ["COOKIE_PASSWORD"] = cookiers_password
if not st.session_state.get('cookier_password', None):
    st.session_state.cookier_password = os.environ["COOKIE_PASSWORD"]

cookies = EncryptedCookieManager(prefix="biogen_", password=st.session_state.cookier_password)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated and cookies.ready():
    if cookies.get('authenticated') == 'True':
        try:
            st.session_state.authenticated = True
            st.session_state.login_time = datetime.datetime.fromisoformat(cookies.get('login_time', ''))
            st.session_state.username = cookies.get('username', '')
            st.rerun()
        except Exception:
            cookies['authenticated'] = 'False'
            cookies.save()
            st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
        <style>
        [data-testid="stAppViewContainer"] { background: linear-gradient(-45deg, #f8fafc, #e2e8f0, #e0f2fe, #f1f5f9); background-size: 400% 400%; animation: gradientBG 15s ease infinite; position: relative; }
        @keyframes gradientBG { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        .shape-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; overflow: hidden; z-index: 0; pointer-events: none; }
        .bg-shape { position: absolute; border-radius: 50%; filter: blur(60px); opacity: 0.5; animation: drift 15s infinite alternate; }
        .shape1 { top: -10%; left: -10%; width: 50vw; height: 50vw; background: rgba(59, 130, 246, 0.4); }
        .shape2 { bottom: -10%; right: -10%; width: 40vw; height: 40vw; background: rgba(16, 185, 129, 0.3); animation-delay: -5s; }
        .shape3 { top: 40%; left: 60%; width: 30vw; height: 30vw; background: rgba(139, 92, 246, 0.2); animation-delay: -10s; }
        @keyframes drift { 0% { transform: translate(0, 0) scale(1); } 100% { transform: translate(30px, 30px) scale(1.1); } }
        div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stVerticalBlock"] { background: rgba(255, 255, 255, 0.7) !important; backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-radius: 24px; padding: 2.5rem 2rem; box-shadow: 0 10px 40px -10px rgba(31, 38, 135, 0.15), inset 0 0 0 1px rgba(255, 255, 255, 0.5); transition: transform 0.3s ease, box-shadow 0.3s ease; position: relative; z-index: 1; }
        div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stVerticalBlock"]:hover { transform: translateY(-5px); box-shadow: 0 20px 40px -10px rgba(31, 38, 135, 0.2), inset 0 0 0 1px rgba(255, 255, 255, 0.6); }
        .stTextInput input { border-radius: 12px !important; border: 1px solid rgba(203, 213, 225, 0.8) !important; background: rgba(255, 255, 255, 0.9) !important; transition: all 0.3s ease !important; }
        .stTextInput input:focus { box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3) !important; border-color: #3b82f6 !important; }
        .stButton button { border-radius: 12px !important; font-weight: 600 !important; letter-spacing: 0.5px !important; transition: all 0.3s ease !important; }
        </style>
        <div class="shape-container"><div class="bg-shape shape1"></div><div class="bg-shape shape2"></div><div class="bg-shape shape3"></div></div>
    """, unsafe_allow_html=True)

    logo_url = "https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505"
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(f'<div style="text-align: center; position: relative; z-index: 1;"><img src="{logo_url}" alt="Logo" style="max-width: 220px; height: auto;"></div>', unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center; color: #1E293B; margin-top: 10px; position: relative; z-index: 1;'> </h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b; position: relative; z-index: 1;'>Sign in to your intelligent bioinformatics workspace</p><br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.container():
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            with st.expander("⚙️ Advanced Settings"):
                usrname_id_login = st.text_input("Project ID (optional)", value="", help="Bind to a specific BioWorker project session")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Sign In", type="primary", width="stretch"):
                app_user = os.environ.get('APP_USER')
                salt = os.environ.get('PASSWORD_SALT')
                
                def get_hashed(pwd, s): return hashlib.sha256((pwd + s).encode('utf-8')).hexdigest()

                is_valid_login = False
                if app_user and os.path.isfile(app_user):
                    try:
                        with open(app_user, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if not line or line.startswith('#'): continue
                                parts = line.split(':', 1)
                                if len(parts) == 2:
                                    file_user, file_pass = parts
                                    if file_user == username:
                                        if (get_hashed(password, salt) if salt else password) == file_pass:
                                            is_valid_login = True
                                        break
                    except Exception: pass
                else:
                    expected_username, expected_password = (app_user.split(':', 1) + [''])[:2] if app_user else ("admin", "admin")
                    if username == expected_username and (get_hashed(password, salt) if salt else password) == expected_password:
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
                    st.error("Invalid credentials. Please try again.")
    st.stop()

else:
    if (datetime.datetime.now() - st.session_state.login_time) > timedelta(days=3):
        st.session_state.authenticated = False
        cookies['authenticated'] = 'False'
        cookies.save()
        st.rerun()
    else:
        if 'session_loaded' not in st.session_state:
            if 'project_id' in cookies and 'project_id' not in st.session_state:
                st.session_state.project_id = cookies['project_id']
            storage.load_session(st.session_state.username, st.session_state)
            st.session_state.session_loaded = True
            if st.session_state.get('processing', False) and 'reconnect_warning_shown' not in st.session_state:
                st.warning("Reconnection detected during an active task. Monitoring session.")
                st.session_state.reconnect_warning_shown = True
                storage.save_session(st.session_state.username, st.session_state)

st.sidebar.image("https://dataweb.biogaip.top/img/bioGAIP%20Logo.png?expires=2552095591&token=864d8025f4c7e8ecb5143aa04688376dbed6d78923d710e58a65b0f11ac3d505", width="stretch")
st.sidebar.subheader("🕹️ Session Control")
col_s1, col_s2 = st.sidebar.columns(2)

with col_s1:
    if st.button("Logout", width="stretch"):
        st.session_state.authenticated = False
        cookies['authenticated'] = 'False'
        cookies.save()
        
        if 'api_process' in st.session_state and hasattr(st.session_state.api_process, 'kill'):
            try: st.session_state.api_process.kill()
            except Exception: pass
            
        keys = list(st.session_state.keys())
        for key in keys:
            if key != 'cookier_password':
                del st.session_state[key]
        st.rerun()

def get_file_prefix():
    pid = st.session_state.get('project_id', 'default')
    return f"{st.session_state.username}_{pid}"

pid_file = os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")

def check_team_pid_running(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f: pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except Exception: return False
    return False

def run_unattended_resume(ctx, _logger):
    """
    Unattended background auto-resume: 
    Generates summary and restarts process_task natively in the background.
    """
    storage = ctx['storage']
    username = ctx['username']
    
    try: os.remove(ctx['team_summary_file'])
    except OSError: pass
    
    _logger.info("[Watchdog] Frontend offline. Initiating unattended background auto-summary...")
    
    user_prompt_history = storage.get_user_prompt_history(username, file_path=ctx['user_prompt_json'])
    temp_session = {}
    storage.load_session(username, temp_session)
    session_file = storage.export_session_to_json(username, temp_session)
    
    content_summary = bg_summary.run_summary(session_file, ctx['model'], ctx['max_summary_content'], user_prompt_history)
    
    chat_msg = f"==============User Orginal task============\n{str(user_prompt_history)}\nCurrent Processing Summary:\n{content_summary}\n"
    chat_content = {"role": "system", "content": f"Previous conversation context summarized below: \n```{chat_msg}```\n. Please proceed with current tasks utilizing this summary."}
    
    with open(ctx['log_file'], 'a') as f: storage.json_safedump(chat_content, f)
    if 'messages' not in temp_session: temp_session['messages'] = []
    temp_session['messages'].append(chat_content)
    storage.save_session(username, temp_session)
    
    _logger.info("[Watchdog] Summary generated. Restarting process_task in background...")
    team = create_team(storage, ctx['persist_dir'], file=ctx['agent_status_file'], team_summary=True, logger=_logger)
    user_message = "Please continue tasks\n" + chat_msg + "\nPlease proceed logically."
    
    stop_team, force_stop = multiprocessing.Event(), multiprocessing.Event()
    pid_file = os.path.join(ctx['persist_dir'], f"{ctx['file_prefix']}.process_pid")
    
    for f in [ctx['team_exit_file'], ctx['team_exit_file'] + '_set', ctx['agent_status_file'], pid_file, ctx['team_summary_file'] + '_no_user_confirm']:
        if os.path.exists(f): os.remove(f)
    open(ctx['log_file'], 'w').close()
    
    if platform.system().lower() != 'windows':
        p = Process(target=process_task, args=(user_message, ctx['log_file'], team, stop_team, force_stop, ctx['agent_status_file'], ctx['team_exit_file'], ctx['team_summary_file'], ctx['max_content'], False, ctx['reward'], storage, _logger, os.getpid()), daemon=True)
        p.start()
        with open(pid_file, 'w') as f: f.write(str(p.pid))
    else:
        p = threading.Thread(target=process_task, args=(user_message, ctx['log_file'], team, stop_team, force_stop, ctx['agent_status_file'], ctx['team_exit_file'], ctx['team_summary_file'], ctx['max_content'], False, ctx['reward'], storage, _logger, None), daemon=True)
        p.start()
        with open(pid_file, 'w') as f: f.write(str(os.getpid()))
        
    _logger.info("[Watchdog] Unattended auto-resume successful!")
    
    threading.Thread(target=summary_watchdog, args=(ctx['team_summary_file'], ctx['team_exit_file'], pid_file, stop_team, force_stop, _logger, ctx, 30, 5), daemon=True).start()


def summary_watchdog(summary_file, exit_file, pid_file, stop_event, force_stop_event, _logger, ctx=None, summary_timeout=30, exit_timeout=35):
    """Monitor unhandled state files. Triggers auto-resume if frontend disconnects."""
    targets = [(summary_file, summary_timeout), (exit_file, exit_timeout)]
    
    while True:
        if not check_team_pid_running(pid_file):
            break
            
        now = time.time()
        terminated = False
        is_summary_timeout = False
        
        for file_path, timeout in targets:
            if os.path.exists(file_path):
                try:
                    if now - os.path.getmtime(file_path) > timeout:
                        _logger.warning(f"Watchdog: Timeout on {file_path}. Terminating orphaned task...")
                        if stop_event: stop_event.set()
                        if force_stop_event: force_stop_event.set()
                        force_kill_process(pid_file, _logger)
                        
                        terminated = True
                        if file_path == summary_file: is_summary_timeout = True
                        break
                except OSError:
                    pass # Safe fallback for race conditions
                    
        if terminated:
            if is_summary_timeout and ctx:
                try:
                    run_unattended_resume(ctx, _logger)
                except Exception as e:
                    _logger.error(f"Failed to auto-resume: {e}")
            break
            
        time.sleep(2)

@st.dialog("Reset Session Warning")
def reset_session_confirm():
    st.warning("This will terminate any running tasks and clear the current chat history. Are you sure?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", key="cancel_reset_btn", width="stretch"):
            st.session_state.show_reset_dialog = False
            st.rerun()
    with col2:
        if st.button("Confirm Reset", type="primary", key="confirm_reset_btn", width="stretch"):
            st.session_state.show_reset_dialog = False
            st.info("Resetting workspace...")
            if 'stop_team' in st.session_state and hasattr(st.session_state.stop_team, 'set'):
                try: st.session_state.stop_team.set()
                except Exception: pass
                
            if 'team_exit_file' in st.session_state:
                try:
                    with open(st.session_state.team_exit_file + '_set', 'w') as f: f.write('')
                except Exception: pass
                
            if 'force_stop' in st.session_state and hasattr(st.session_state.force_stop, 'set'): 
                try: st.session_state.force_stop.set()
                except Exception: pass
            
            time.sleep(0.5)
            force_kill_process(pid_file, logger)
            
            if 'team_exit_file' in st.session_state and os.path.exists(st.session_state.team_exit_file):
                try: os.remove(st.session_state.team_exit_file)
                except Exception: pass
                
            if 'team' in st.session_state: del st.session_state.team
            
            st.session_state.processing = False
            st.session_state.show_refresh_button = True
            
            if 'project_id' in st.session_state:
                try:
                    project_status = get_project_status(st.session_state.project_id, API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
                    if isinstance(project_status, dict) and project_status.get('status') == 'running':
                        task_id = project_status.get('current_task_id')
                        if task_id: requests.post(f"{os.environ.get('API_URL')}/tasks/{task_id}/kill", headers={"x-api-key": os.environ.get('API_KEY')})
                except Exception: pass
            
            st.session_state.messages = []
            st.session_state.prompt_history = ""
            storage.delete_session(st.session_state.username, st.session_state)
            
            st.session_state.log_file = os.path.join(persist_dir, f"{get_file_prefix()}_log.ndjson")
            st.session_state.input_file = os.path.join(persist_dir, f"{get_file_prefix()}_input.txt")
            open(st.session_state.log_file, 'w').close()
            open(st.session_state.input_file, 'w').close()
            
            for k in ['pending_prompt', 'pending_prompt_type', 'input_prompt']:
                if k in st.session_state: del st.session_state[k]
                
            storage.save_session(st.session_state.username, st.session_state)
            st.rerun()

with col_s2:
    if st.button("Reset", width="stretch"):
        st.session_state.show_reset_dialog = True

if st.session_state.get("show_reset_dialog", False):
    reset_session_confirm()

st.sidebar.divider()
st.sidebar.subheader("📦 Workspace Manager")

def create_workspace_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(persist_dir):
            for file in files:
                file_path = os.path.join(root, file)
                z.write(file_path, os.path.relpath(file_path, persist_dir))
    buf.seek(0)
    return buf

st.sidebar.download_button(
    label="📤 Export Workspace",
    data=create_workspace_zip(),
    file_name=f"biogaip_workspace_{st.session_state.get('username', 'export')}.zip",
    mime="application/zip",
    width="stretch"
)

@st.dialog("📥 Import Workspace")
def import_workspace_dialog():
    st.warning("⚠️ **Experimental Feature**\nImporting data from unknown sources poses significant security risks.")
    uploaded_zip = st.file_uploader("Upload Workspace ZIP", type=["zip"])
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", key="cancel_import_btn", width="stretch"):
            st.session_state.show_import_dialog = False
            st.rerun()
    with col2:
        if uploaded_zip and st.button("Confirm Import & Restart", type="primary", width="stretch"):
            st.session_state.show_import_dialog = False
            try:
                with zipfile.ZipFile(uploaded_zip, "r") as z: z.extractall(persist_dir)
                st.success("Import successful. System restarting.")
                time.sleep(1)
                st.session_state.authenticated = False
                cookies['authenticated'] = 'False'
                cookies.save()
                for key in list(st.session_state.keys()):
                    if key != 'cookier_password': del st.session_state[key]
                st.rerun()
            except Exception as e: 
                st.error(f"Import failed: {str(e)}")

if st.sidebar.button("📥 Import Workspace", width="stretch"): 
    st.session_state.show_import_dialog = True

if st.session_state.get("show_import_dialog", False):
    import_workspace_dialog()

if "api_setup_done" not in st.session_state:
    api_url = os.environ.get('API_URL')
    api_key = os.environ.get('API_KEY')
    if not api_url or not api_key: st.session_state.api_setup_done = False
    else: st.session_state.api_setup_done = check_api(st.session_state, remote_tool_loaded, logger)

if not st.session_state.get('api_setup_done', False):
    st.markdown("<h2 style='text-align: center;'>BioWorker API Setup Wizard</h2>", unsafe_allow_html=True)
    st.info("⚠️ Security Warning: Ensure environment is secure.")
    tab1, tab2, tab3 = st.tabs(["🌐 Manual Setup", "🖥️ SSH Setup", "🔗 Pair Code Setup"])

    with tab1:
        api_url_input = st.text_input("Enter bioWorker API URL", value=os.environ.get('API_URL', ''))
        api_key_input = st.text_input("Enter bioWorker API Key", value=os.environ.get('API_KEY', ''), type="password")
        with st.expander("Advanced Settings"): usrname_id_login = st.text_input("Project ID (optional)", value=st.session_state.get('project_id', ""))
        if st.button("Set API Credentials", type="primary"):
            logger.info(f"Attempting to set API credentials: URL={api_url_input}, Key={'*' * len(api_key_input)}, ProjectID={usrname_id_login}")
            if api_url_input and api_key_input:
                os.environ['API_URL'] = api_url_input
                os.environ['API_KEY'] = api_key_input
                reset_project_id = usrname_id_login != '' and usrname_id_login is not None and usrname_id_login != st.session_state.get('project_id', '')
                if reset_project_id:
                    st.session_state.project_id = usrname_id_login
                    os.environ['PROJECT_ID'] = st.session_state.project_id
                if check_api(st.session_state, remote_tool_loaded, logger, reset_project_id=reset_project_id):
                    st.success("API credentials verified successfully!")
                    st.session_state.api_setup_done = True
                    if reset_project_id: st.session_state.project_id = usrname_id_login
                    st.rerun()
                else:
                    st.error("Invalid API credentials or server unreachable.")

    with tab2:
        st.warning("Experimental feature.")
        server_ip = st.text_input("Server IP")
        username = st.text_input("User Name")
        port = st.text_input("Port", value="22")
        ssh_password = st.text_input("SSH Password", type="password")
        read_directory = st.text_input("Directory allowed to read")
        read_write_directory = st.text_input("Directory allowed to read & write")
        work_dir = st.text_input("Working Directory")
        temp_dir = st.text_input("Temporary Directory")
        if "ssh_api_key" not in st.session_state: st.session_state.ssh_api_key = ""
        api_key = st.text_input("bioWorker API Key", value=st.session_state.ssh_api_key, type="password")
        if st.button("Generate API Key"):
            st.session_state.ssh_api_key = secrets.token_hex(64)
            st.rerun()
        with st.expander("Advanced Settings"):
            use_sandbox = st.selectbox('Sandbox Mode', ['Disabled', 'bubblewrap', 'landlock'], index=0)
            bioworker_port = st.text_input("Bioworker Port", value="38000")
            max_task = st.number_input("Maximum tasks", min_value=1, max_value=100, value=1, step=1)
            web_admin_panel = st.checkbox("Enable web admin panel", value=False)
        
        if st.button("Initialize via SSH", type="primary"):
            if server_ip and username and port and ssh_password and api_key:
                use_sandbox_type = None if use_sandbox == 'Disabled' else use_sandbox
                success, output, error_output = api_set2(server_ip, username, port, ssh_password, api_key, read_directory or '', read_write_directory or '', work_dir or '', bioworker_port=bioworker_port, use_sandbox_type=use_sandbox_type, temp_dir=temp_dir or '', max_task=max_task, web_admin=web_admin_panel)
                if not success:
                    st.error("Setup failed.")
                    if 'api_process' in st.session_state: st.session_state.api_process.kill()
                    st.stop()
                os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                os.environ['API_KEY'] = api_key
                if check_api(st.session_state, remote_tool_loaded, logger):
                    st.success("API setup successful!")
                    st.session_state.api_setup_done = True
                    check_model()
                    st.rerun()
                else: st.error("API validation failed.")

    with tab3:
        st.error("Disabled for security reasons.")
    st.stop()

if "setup_done" not in st.session_state:
    st.session_state.setup_done = True
    if 'input_counter' not in st.session_state: st.session_state.input_counter = 0 
    if 'processing' not in st.session_state: st.session_state.processing = False
    if 'project_id' not in st.session_state:
        try:
            st.session_state.project_id = asyncio.run(execute_shell_command_via_api(command=''))
            os.environ['PROJECT_ID'] = st.session_state.project_id
        except Exception: pass
        if remote_tool_loaded:
            try: _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ.get('PROJECT_ID', ''), api_base_url=os.environ.get('API_URL', ''), api_key=os.environ.get('API_KEY', ''))
            except Exception: pass
    
    st.session_state.log_file = os.path.join(persist_dir, f"{get_file_prefix()}_log.ndjson")
    st.session_state.input_file = os.path.join(persist_dir, f"{get_file_prefix()}_input.txt")
    if not os.path.exists(st.session_state.log_file): open(st.session_state.log_file, 'w').close()
    if not os.path.exists(st.session_state.input_file): open(st.session_state.input_file, 'w').close()
    st.session_state.agent_status_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
    st.session_state.prompt_history = st.session_state.get('prompt_history', "")

@st.dialog("Terminate Task")
def kill_task_confirm(task_id):
    if not task_id: return
    st.warning("This will force terminate the active remote task. Continue?")
    message = st.text_input("Optional termination reason:")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", key="cancel_kill_btn", width="stretch"): 
            st.session_state.show_kill_dialog = False
            st.rerun()
    with col2:
        if st.button("Confirm", type="primary", key="confirm_kill_btn", width="stretch"):
            st.session_state.show_kill_dialog = False
            try:
                requests.post(f"{os.environ['API_URL']}/tasks/{task_id}/kill", json={"message": message}, headers={"x-api-key": os.environ['API_KEY']}).raise_for_status()
                st.success("Signal dispatched successfully.")
                time.sleep(1)
            except Exception as e: st.error(f"Failed to terminate task: {str(e)}")
            st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💻 BioWorker Dashboard")

if os.environ.get('API_URL', '') != '' and os.environ.get('API_KEY', '') != '':
    short_pid = st.session_state.get('project_id', '')[:8] + "..." if len(st.session_state.get('project_id', '')) > 8 else st.session_state.get('project_id', '')
    st.sidebar.caption(f"**Project ID:** `{short_pid}`")
    
    def render_dashboard_content():
        try:
            stats_resp = requests.get(f"{os.environ.get('API_URL')}/stats", headers={"x-api-key": os.environ.get('API_KEY')}, params={"project_id": st.session_state.get('project_id', '')}, timeout=2)
            if stats_resp.status_code == 200:
                stats = stats_resp.json()
                sys_mem = stats.get('system', {}).get('mem_percent', 0)
                proj_cpu = stats.get('project', {}).get('cpu_percent', 0)
                met1, met2 = st.columns(2)
                met1.metric(label="Server RAM", value=f"{sys_mem}%")
                met2.metric(label="Task CPU", value=f"{proj_cpu}%")
        except Exception: pass 

        project_status = get_project_status(st.session_state.get('project_id', ''), API_URL=os.environ.get('API_URL'), API_KEY=os.environ.get('API_KEY'))
        if isinstance(project_status, dict):
            status = project_status.get('status', 'unknown')
            current_command = project_status.get('current_command', 'N/A')
            status_md = f"**Status:** {'🟢' if status == 'running' else '💤'} {status.capitalize()}\n\n"
            if status == 'running': status_md += f"**Current Command:**\n```bash\n{current_command}\n```"
            st.info(status_md)
            if status == 'running':
                task_id = project_status.get('current_task_id')
                st.session_state.current_task_id = task_id
                if task_id and st.button("🛑 Force Kill Task", width="stretch", key="dashboard_force_kill"):
                    st.session_state.show_kill_dialog = True
                    st.rerun()

    if hasattr(st, "fragment"):
        @st.fragment(run_every=3)
        def dashboard_fragment(): render_dashboard_content()
        with st.sidebar: dashboard_fragment()
    else:
        with st.sidebar: render_dashboard_content()
            
    st.sidebar.divider()
    st.sidebar.subheader("API Server Manager")
    if st.sidebar.button("Stop API Server", width="stretch"):
        try: shutdown_server(host=os.environ.get('API_URL'), api_key=os.environ.get('API_KEY'))
        except Exception: pass
        if 'api_process' in st.session_state and hasattr(st.session_state.api_process, 'kill'):
            try: st.session_state.api_process.kill()
            except Exception: pass
        os.environ['API_URL'], os.environ['API_KEY'] = '', ''
        st.session_state.api_setup_done = False
        st.rerun()
        
    st.sidebar.markdown(f"[🔗 Open bioWorker Control Panel]({os.environ.get('API_URL')})")

if st.session_state.get('show_kill_dialog', False):
    kill_task_confirm(st.session_state.get('current_task_id', None))

st.sidebar.markdown(f"<div style='position: fixed; bottom: 10px; font-size: 10px; color: grey;'>Core Version: {version_data}</div>", unsafe_allow_html=True)

if "messages" not in st.session_state: st.session_state.messages = []
if "message_processed_front_ui_uuid" not in st.session_state: st.session_state.message_processed_front_ui_uuid = []

welcome_placeholder = st.empty()

if not st.session_state.messages and st.session_state.get('api_setup_done', False):
    with welcome_placeholder.container():
        st.markdown("""
            <style>
            .welcome-bg-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background-image: radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.08), transparent 30%), radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.08), transparent 30%), linear-gradient(rgba(15, 23, 42, 0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(15, 23, 42, 0.03) 1px, transparent 1px); background-size: 100% 100%, 100% 100%, 40px 40px, 40px 40px; z-index: -1; pointer-events: none; }
            .welcome-title-anim { background: linear-gradient(90deg, #1E293B, #3B82F6, #10B981, #1E293B); background-size: 300% 100%; -webkit-background-clip: text; -webkit-text-fill-color: transparent; animation: gradient-shift 8s ease infinite; }
            @keyframes gradient-shift { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
            </style>
            <div class="welcome-bg-container"></div><div style='margin-top: 5rem;'></div>
            <h1 class='welcome-title-anim' style='text-align: center; font-size: 3rem; font-weight: 800;'>BioGAIP Workspace</h1>
            <p style='text-align: center; color: #64748b; margin-bottom: 3rem; font-size: 1.1rem;'>Select an intelligent template below or begin typing to interact with the agents.</p>
        """, unsafe_allow_html=True)
        cols = st.columns(2)
        for i, starter in enumerate(starters):
            with cols[i % 2]:
                if st.button(f"✨ {starter['label']}", key=f"starter_{i}", width="stretch", help=starter['message']):
                    st.session_state.messages.append({"role": "user", "content": starter["message"]})
                    storage.save_session(st.session_state.username, st.session_state)
                    st.rerun()
else:
    welcome_placeholder.empty()

for message in st.session_state.messages:
    message_uuid = message.get('message_uuid', None)
    if message["role"] != "user_proxy" and message["content"].startswith("@user_proxy:") and message["content"].startswith("user_proxy:"): continue
    if message["role"] == "thought":
        with st.expander(f"🧠 Internal Thought Stream: {message['source']}"): st.markdown(message["content"])
    else:
        with st.chat_message(message["role"], avatar=get_avatar(message["role"])):
            if "cleaned_content" not in message or "file_blocks" not in message:
                content = message["content"]
                message["file_blocks"] = re.findall(r'<uploaded_file name="(.*?)" ext="(.*?)"\>(.*?)</uploaded_file>', content, re.DOTALL)
                message["cleaned_content"] = re.sub(r'<uploaded_file name=".*?" ext=".*?"\>(.*?)</uploaded_file>', '', content, flags=re.DOTALL)
            
            st.markdown(message["cleaned_content"].strip())
            for name, ext, file_content in message["file_blocks"]:
                with st.expander(f"📄 Attached Document: {name}"): st.code(file_content.strip(), language=ext.lower() if ext.lower() in ['python', 'json', 'html', 'md', 'txt'] else None)
    if message_uuid: st.session_state.message_processed_front_ui_uuid.append(message_uuid)

if 'last_uploaded_files' not in st.session_state: st.session_state.last_uploaded_files = set()
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
st.session_state.init_messaged = False

placeholder_text = "Type your response here..." if st.session_state.get('waiting_for_user_input', False) else "Message the agents..."
if st.session_state.get('processing', False) and not st.session_state.get('waiting_for_user_input', False): placeholder_text = "Task in progress. Stop the task to input text..."

user_prompt_json = os.path.join(persist_dir, f"{get_file_prefix()}_input.ujson")
chat_file_types = ['txt', 'md', 'html', 'pdf', 'htm', 'py', 'js', 'sh', 'docx', 'xlsx', 'pptx', 'java', 'c', 'cpp', 'h', 'rb', 'pl', 'php', 'go', 'rs', 'kt', 'swift', 'r', 'm', 'lua', 'cs', 'ts', 'scala', 'groovy', 'perl', 'bat', 'cmd', 'ps1', 'pm', 'vb', 'f', 'f90', 'jl', 'hs', 'Rmd', 'ipynb']

message = None
uploaded_files = []

@st.dialog("Review Strategy Summary", width="large")
def review_strategy_summary_dialog():
    edited = st.text_area("Adjust the strategic recap before continuing:", value=st.session_state.get("chat_summary_message", ""), height=300)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel & Abort", key="cancel_summary_btn", width="stretch"):
            st.session_state.is_team_summary_active = False
            st.session_state.user_required_summary = False
            st.session_state.finish_summary = True
            st.session_state.automatic_start = False
            st.rerun()
    with col2:
        if st.button("Confirm Strategy", type="primary", key="confirm_summary_btn", width="stretch"):
            st.session_state.chat_summary_message = edited
            st.session_state.user_confirmed_summary = True
            st.session_state.automatic_start = True
            st.rerun()

with st.bottom:
    show_stop_button = st.session_state.get('processing', False)
    show_refresh_button = show_stop_button or st.session_state.get('show_refresh_button', False)

    if show_stop_button or show_refresh_button:
        with st.container(key="chat_controls"):
            ctrl_stop, ctrl_refresh = st.columns([1, 1])
            with ctrl_stop:
                if show_stop_button:
                    if st.button("🛑", key="stop_team_button", help="Stop task"):
                        project_status = get_project_status(st.session_state.get('project_id', ''), os.environ.get('API_URL', ''), os.environ.get('API_KEY', ''))
                        if isinstance(project_status, dict) and project_status.get('status') == 'running':
                            st.toast("Please stop the active task manually in the control panel.", icon="⚠️")
                        else:
                            st.toast("Stopping the active agent session...", icon="⚠️")
                            st.session_state.prompt_history = "\n\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
                            storage.save_session(st.session_state.username, st.session_state)
                            team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
                            st.session_state.team_exit_file = team_exit_file 
                            try: st.session_state.stop_team.set()
                            except AttributeError:
                                st.session_state.team_exit_file_set = team_exit_file + '_set'
                                try:
                                    with open(st.session_state.team_exit_file_set, 'w') as f: f.write('')
                                except Exception: pass
                            
                            wait_cycles = 0
                            while not os.path.exists(st.session_state.team_exit_file) and wait_cycles < 3:
                                time.sleep(1)
                                wait_cycles += 1
                                
                            if not os.path.exists(st.session_state.team_exit_file): force_kill_process(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid"), logger)
                            else:
                                try: os.remove(st.session_state.team_exit_file)
                                except Exception: pass
                                
                            if 'team' in st.session_state: del st.session_state.team
                            st.session_state.processing = False
                            st.session_state.show_refresh_button = True
                            st.rerun()

            with ctrl_refresh:
                @st.dialog("Refresh Session")
                def _refresh_session_confirm():
                    st.warning("Are you sure you want to trigger a session refresh?")
                    clear_history = st.checkbox("Clear UI session history", value=False)
                    automatic_start = st.checkbox("Automatically resume task post-refresh (bypass review)", value=True)
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Cancel", key="cancel_refresh_btn", width="stretch"):
                            st.session_state.show_refresh_dialog = False
                            st.rerun()
                    with col2:
                        if st.button("Confirm", key="confirm_refresh_btn", type="primary", width="stretch"):
                            st.session_state.show_refresh_dialog = False
                            st.session_state.run_summary = True
                            st.session_state.clear_session_content = clear_history
                            st.session_state.automatic_start = automatic_start
                            st.session_state.user_required_summary = not automatic_start
                            st.session_state.processing = False
                            st.rerun()

                if show_refresh_button:
                    if st.button("🔃", key="refresh_button", help="Refresh session"):
                        logger.info("User initiated session refresh.")
                        ## if team is runing, ask user to stop the team first
                        if st.session_state.get('processing', False):
                            st.toast("Please stop the active session before refreshing. You can click 🛑 to stop session.", icon="⚠️", duration=30)
                            st.rerun()
                        logger.info("Preparing for session refresh...")
                        st.session_state.user_confirmed_summary = False
                        st.session_state.user_required_summary = True
                        st.session_state.team_summary_file = os.path.join(persist_dir, f"{get_file_prefix()}.summary_team")
                        st.session_state.team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
                        st.session_state.show_refresh_dialog = True
                        logger.info("Session refresh dialog triggered.")
                
                if st.session_state.get("show_refresh_dialog", False):
                    _refresh_session_confirm()

                if st.session_state.get('run_summary', False):
                    st.toast("Session refresh executing...", icon="🔄")
                    with open(st.session_state.team_exit_file + '_set', 'w') as f: f.write('') 
                    with open(st.session_state.team_summary_file, 'w') as f: f.write('')
                    
                    time.sleep(1)
                    if not os.path.exists(st.session_state.team_exit_file) and check_team_pid_running(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")):
                        force_kill_process(os.path.join(persist_dir, f"{get_file_prefix()}.process_pid"), logger)
                    
                    if 'team' in st.session_state: del st.session_state.team
                    st.session_state.run_summary = False
                    st.rerun()

    chat_value = st.chat_input(placeholder_text, key="main_chat_input", accept_file="multiple", file_type=chat_file_types)
    if chat_value is not None:
        if isinstance(chat_value, str): message = chat_value
        else:
            message = getattr(chat_value, "text", "") or ""
            uploaded_files = list(getattr(chat_value, "files", None) or [])
        if 'automatic_start' in st.session_state: st.session_state.automatic_start = True
        if message: storage.safe_append(user_prompt_json, {'role': 'user', 'message': message}, username=st.session_state.username)

if message is not None:
    full_message = message.strip() if message else ""
    file_contents = []
    if uploaded_files:
        for f in uploaded_files:
            content = read_uploaded_file(f)
            if content: file_contents.append(content)
            st.session_state.last_uploaded_files.add(f.name)
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
        storage.save_session(st.session_state.username, st.session_state)
        st.session_state.uploader_key += 1
        st.rerun()

team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
team_summary_file = os.path.join(persist_dir, f"{get_file_prefix()}.summary_team")
pid_file = os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")

team_summary = os.path.exists(team_summary_file) or st.session_state.get('is_team_summary_active', False)

if "messages" in st.session_state and st.session_state.messages:
    last_user_message = next((msg for msg in reversed(st.session_state.messages) if msg["role"] == "user" and not msg.get("processed")), None)
    
    if (last_user_message is not None or team_summary) and (not st.session_state.get('processing', False) or os.path.exists(team_exit_file) or not check_team_pid_running(pid_file)):
        user_message = last_user_message["content"] if last_user_message else "Please continue tasks"
        if last_user_message: last_user_message["processed"] = True
        storage.save_session(st.session_state.username, st.session_state)
        
        st.session_state.processing = True
        st.session_state.processing_start_time = time.time()
        st.session_state.last_save_time = time.time()
        
        st.session_state.stop_team = multiprocessing.Event()
        st.session_state.force_stop = multiprocessing.Event()
        st.session_state.agent_status_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
        st.session_state.team_exit_file = team_exit_file 
        st.session_state.pid_file = pid_file
        
        if os.path.exists(team_exit_file) or not check_team_pid_running(pid_file):
            if not team_summary: 
                if 'team' in st.session_state: del st.session_state.team
                try: os.remove(team_exit_file)
                except Exception: pass
            
        st.session_state.team_summary_file = team_summary_file
        st.session_state.max_content = sys_config.get('max_content', 1000) if 'sys_config' in locals() or 'sys_config' in globals() else 1000
        st.session_state.max_summary_content = sys_config.get('max_summary_content', 10000) if 'sys_config' in locals() or 'sys_config' in globals() else 10000
        
        if os.path.exists(team_summary_file):
            logger.info(f"============== Detected existing team summary file: {team_summary_file}. Activating team summary mode.===============")
            logger.info(f"             Removing team summary file to trigger re-analysis:             ")
            os.remove(team_summary_file)
            st.session_state.is_team_summary_active = True
            team_summary = True
            if 'team' in st.session_state:
                ### read pid and check if team is running, if not, delete team from session state
                if not check_team_pid_running(pid_file):
                    logger.info(f"[app.py] Detected team summary file but team process not running. Cleaning up session state.")
                    del st.session_state.team
                else: 
                    # kill the team process to ensure a fresh start
                    logger.info(f"[app.py] Detected team summary file and team process running. Terminating existing team process to ensure a fresh start.")
                    force_kill_process(pid_file, logger)
                    st.toast("[app.py] Existing team process terminated. Preparing to restart with new summary.", icon="⚠️")
                if check_team_pid_running(pid_file):
                    logger.error(f"[app.py] After attempting to terminate, team process is still running. This may indicate a problem.")
                else:
                    logger.info(f"[app.py] Team process successfully terminated. Ready to restart with new summary.")
                    del st.session_state.team
        elif st.session_state.get('is_team_summary_active', False):
            team_summary = True
        else: 
            team_summary = False

        if os.path.exists(team_summary_file + '_no_user_confirm'): os.remove(team_summary_file + '_no_user_confirm')

        if 'team' not in st.session_state:
            st.session_state.team = create_team(storage, persist_dir, file=st.session_state.agent_status_file, team_summary=team_summary, logger=logger)
            st.session_state.load_history = not team_summary and not st.session_state.get('finish_summary', False)
            if st.session_state.load_history: st.session_state.finish_summary = False
            
            if team_summary:
                logger.info("[app.py] Team summary mode activated. Preparing to analyze context and generate strategic summary.")
                ag_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
                if os.path.exists(ag_file): os.remove(ag_file)
                
                with st.spinner("Analyzing context and generating strategic summary..."):
                    user_prompt_history = storage.get_user_prompt_history(st.session_state.username, file_path=user_prompt_json)
                    session_file_for_summary = storage.export_session_to_json(st.session_state.username, st.session_state)
                    logger.info(f"[app.py] Session file for summary: {session_file_for_summary}")
                    
                    _model = content_summary_model if 'content_summary_model' in globals() else None
                    content_summary = bg_summary.run_summary(session_file_for_summary, _model, st.session_state.max_summary_content, user_prompt_history)
                    
                    st.session_state.chat_summary_message = f"==============User Orginal task============\n{str(user_prompt_history)}\nCurrent Processing Summary:\n{content_summary}\n"
                    st.session_state.content_summary_raw = content_summary
                    st.session_state.user_prompt_history_raw = str(user_prompt_history)
        if 'team' in st.session_state and team_summary:
            logger.error("[app.py] Team summary mode active but team not stopped? Its a bug.")

        if team_summary and not st.session_state.get('finish_summary', False):
            logger.info("[app.py] Team summary mode active. Awaiting proceed with tasks.")
            if not st.session_state.get("user_confirmed_summary", False) and st.session_state.get("user_required_summary", False):
                st.session_state.processing = False 
                review_strategy_summary_dialog()
                st.stop() 
            
            if st.session_state.get("user_confirmed_summary", False) or not st.session_state.get("user_required_summary", False):
                if st.session_state.get("user_confirmed_summary", False):
                    st.toast("🚀 Strategy confirmed! Resuming tasks...", icon="🚀")
                    
                if "user_required_summary" in st.session_state: del st.session_state.user_required_summary
                chat_content = {"role": "system", "content": f"Previous conversation context summarized below: \n```{st.session_state.get('chat_summary_message')}```\n. Please proceed with current tasks utilizing this summary."}
                with open(st.session_state.log_file, 'a') as f: storage.json_safedump(chat_content, f)
                st.session_state.messages.append(chat_content)
                st.session_state.finish_summary = True
                st.session_state.processing = True 
                
                user_message = user_message + f"==============User Orginal task============\n{st.session_state.get('user_prompt_history_raw', '')}\nCurrent Processing Summary:\n{st.session_state.get('content_summary_raw', '')}\n\nPlease proceed logically."
                st.session_state.user_confirmed_summary = False
            
            if not st.session_state.get('finish_summary', False):
                ## bug log
                logger.error("[app.py] Team summary mode active but finish_summary not set? Its a bug.")

        if not team_summary or st.session_state.get('finish_summary', False):
            should_start_task = st.session_state.get('automatic_start', True)
            
            st.session_state.is_team_summary_active = False 
            st.session_state.finish_summary = False
            if 'automatic_start' in st.session_state: del st.session_state.automatic_start
            
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
                    st.session_state.messages.append({"role": "system", "content": f"Context summarization marker: \n```{st.session_state.get('chat_summary_message', '')}```\n. Continue."})
                st.session_state.trigger_browser_reload = True
                
            storage.save_session(st.session_state.username, st.session_state)
            
            if should_start_task: 
                sucessfulExecutate_reward = sys_config.get('sucessfulExecutate_reward', 10) if 'sys_config' in locals() or 'sys_config' in globals() else 10
                if platform.system().lower() != 'windows':
                    process_p = Process(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, os.getpid()), daemon=True)
                    process_p.start()
                    with open(pid_file, 'w') as f: f.write(str(process_p.pid))
                else:
                    process_p = threading.Thread(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, None), daemon=True)
                    process_p.start()
                    with open(pid_file, 'w') as f: f.write(str(os.getpid()))
                
                # whatch dog thread to monitor summary file and exit file
                wd_ctx = {
                    'storage': storage,
                    'persist_dir': persist_dir,
                    'username': st.session_state.username,
                    'file_prefix': get_file_prefix(),
                    'user_prompt_json': user_prompt_json,
                    'max_summary_content': st.session_state.max_summary_content,
                    'log_file': st.session_state.log_file,
                    'agent_status_file': st.session_state.agent_status_file,
                    'team_exit_file': st.session_state.team_exit_file,
                    'team_summary_file': st.session_state.team_summary_file,
                    'max_content': st.session_state.max_content,
                    'reward': sucessfulExecutate_reward,
                    'model': content_summary_model if 'content_summary_model' in globals() else None
                }         
                threading.Thread(
                    target=summary_watchdog,
                    args=(
                        st.session_state.team_summary_file, 
                        st.session_state.team_exit_file, 
                        pid_file, 
                        st.session_state.stop_team, 
                        st.session_state.force_stop, 
                        logger,
                        wd_ctx, # Inject the context
                        30, # Summary timeout 30s (gives frontend enough time if online)
                        5   # Exit file timeout 5s
                    ),
                    daemon=True
                ).start()
                logger.info("[app.py] Task processing initiated in background.")
                if 'init_processing' in st.session_state: st.session_state.init_processing = False
                
            st.rerun()

if st.session_state.get('processing', False):
    waiting_placeholder = st.empty()
    elapsed = int(time.time() - st.session_state.get('processing_start_time', time.time()))
    
    if st.session_state.get('waiting_for_user_input', False):
        spinner_html = f"""
        <div style="display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #fffbeb, #fef3c7); padding: 14px 20px; border-radius: 10px; border: 1px solid #fcd34d; box-shadow: 0 4px 12px rgba(245, 158, 11, 0.1); margin: 8px 0; transition: all 0.3s ease;">
            <div style="font-size: 22px; margin-right: 16px; animation: gentle-pulse 2s infinite;">⚠️</div>
            <div style="flex-grow: 1; font-family: system-ui, -apple-system, sans-serif;">
                <div style="font-weight: 700; color: #92400e; font-size: 14px; margin-bottom: 2px;">Action Required: User Input Needed</div>
                <div style="font-size: 13px; color: #b45309;">Please provide your response in the chat input below to resume the workflow.</div>
            </div>
            <style>@keyframes gentle-pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}</style>
        </div>
        """
    else:
        spinner_html = f"""
        <div style="display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #f8fafc, #f1f5f9); padding: 14px 20px; border-radius: 10px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(15, 23, 42, 0.04); margin: 8px 0;">
            <div style="width: 20px; height: 20px; border: 3px solid rgba(59, 130, 246, 0.15); border-top-color: #3b82f6; border-radius: 50%; animation: bio-spin 1s linear infinite; margin-right: 14px;"></div>
            <div style="flex-grow: 1; font-family: system-ui, -apple-system, sans-serif;">
                <div style="font-weight: 600; color: #0f172a; font-size: 14px; margin-bottom: 2px;">Agents are actively processing data...</div>
                <div style="font-size: 12px; color: #64748b;">Analyzing context and generating intelligent responses</div>
            </div>
            <div style="font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px; font-weight: 600; color: #0f172a; background: #ffffff; padding: 4px 8px; border-radius: 6px; border: 1px solid #cbd5e1;">
                ⏳ {elapsed}s
            </div>
            <style>@keyframes bio-spin {{ to {{ transform: rotate(360deg); }} }}</style>
        </div>
        """
        
    waiting_placeholder.markdown(spinner_html, unsafe_allow_html=True)
    
    updated = False
    if 'message_processed_uuid' not in st.session_state.keys(): st.session_state.message_processed_uuid = []

    if os.path.exists(st.session_state.log_file) and os.path.getsize(st.session_state.log_file) > 0:
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
                    elif item.get('type') == 'toast': updated = True
                    elif item.get('type') == 'stream_update':
                        if st.session_state.messages and st.session_state.messages[-1].get('role') == item['source']:
                            st.session_state.messages[-1]['content'] = item['content']
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

    if updated:
        storage.save_session(st.session_state.username, st.session_state)
        st.session_state.last_save_time = time.time()
        st.rerun()
    else:
        if time.time() - st.session_state.get('last_save_time', 0) > 600:
            storage.save_session(st.session_state.username, st.session_state)
            st.session_state.last_save_time = time.time()
        time.sleep(1.5)
        st.rerun()