import os
import random
import logging
import asyncio
import streamlit as st
from autogen_core import EVENT_LOGGER_NAME
from bioGen.web_v2.storage import get_storage
from bioGen.web_v2.utils import LLMUsageTracker
from bioGen.biogen import *
from modules.utils import get_file_prefix

def init_environment():
    logger = logging.getLogger(EVENT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    llm_usage = LLMUsageTracker()
    logger.handlers = [llm_usage]
    version_data = 'v1.3.4'
    
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

    return logger, persist_dir, storage, version_data

def handle_browser_reload(storage):
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

def render_global_css_and_splash():
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

def initialize_session_state(persist_dir):
    if "setup_done" not in st.session_state:
        st.session_state.setup_done = True
        if 'input_counter' not in st.session_state: st.session_state.input_counter = 0 
        if 'processing' not in st.session_state: st.session_state.processing = False
        if 'project_id' not in st.session_state:
            try:
                st.session_state.project_id = asyncio.run(execute_shell_command_via_api(command=''))
                os.environ['PROJECT_ID'] = st.session_state.project_id
            except Exception: pass
            if 'remote_tool_loaded' in globals() and remote_tool_loaded:
                try: _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ.get('PROJECT_ID', ''), api_base_url=os.environ.get('API_URL', ''), api_key=os.environ.get('API_KEY', ''))
                except Exception: pass
        
    st.session_state.log_file = os.path.join(persist_dir, f"{get_file_prefix()}_log.ndjson")
    st.session_state.input_file = os.path.join(persist_dir, f"{get_file_prefix()}_input.txt")
    if not os.path.exists(st.session_state.log_file): open(st.session_state.log_file, 'w').close()
    if not os.path.exists(st.session_state.input_file): open(st.session_state.input_file, 'w').close()
    st.session_state.agent_status_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
    st.session_state.prompt_history = st.session_state.get('prompt_history', "")

    if "messages" not in st.session_state: st.session_state.messages = []
    if "message_processed_front_ui_uuid" not in st.session_state: st.session_state.message_processed_front_ui_uuid = []