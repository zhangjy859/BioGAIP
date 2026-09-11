import os
import sys
import time
import socket
import threading
import subprocess
import shutil
import string
import random
import copy
import yaml
import atexit
import logging
import signal
import streamlit as st

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BioGAIP-Launcher")

_ACTIVE_PROCESSES = set()
_TEMP_PATHS = set()

def kill_process_tree(p):
    try:
        if sys.platform == "win32":
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(p.pid, signal.SIGKILL)
        p.kill()
        p.wait(timeout=2)
    except Exception as e:
        logger.error(f"Failed to kill process tree: {e}")

def cleanup_all_resources():
    for p in list(_ACTIVE_PROCESSES):
        kill_process_tree(p)
    for path in list(_TEMP_PATHS):
        try:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                logger.info(f"Cleaned up temporary path: {path}")
        except Exception as e:
            logger.error(f"Failed to clean up path {path}: {e}")

atexit.register(cleanup_all_resources)

def stop_current_session():
    if 'bypass_process' in st.session_state and st.session_state.bypass_process:
        p = st.session_state.bypass_process
        logger.info("Terminating running BioGAIP process tree...")
        kill_process_tree(p)
        if p in _ACTIVE_PROCESSES:
            _ACTIVE_PROCESSES.remove(p)
        st.session_state.bypass_process = None
        logger.info("Process terminated successfully.")

def get_biogaip_exe():
    exe_dir = os.path.dirname(sys.executable)
    paths = [
        os.path.join(exe_dir, 'Scripts', 'biogaip.exe'),
        os.path.join(exe_dir, 'Scripts', 'biogaip'),
        os.path.join(exe_dir, 'bin', 'biogaip.exe'),
        os.path.join(exe_dir, 'bin', 'biogaip'),
        os.path.join(exe_dir, 'biogaip.exe'),
        os.path.join(exe_dir, 'biogaip')
    ]
    for p in paths:
        if os.path.exists(p):
            logger.info(f"Found executable at: {p}")
            return p
    logger.error("Executable not found in any of the expected paths.")
    return None

def is_port_occupied(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def stream_process_logs(pipe, log_file_path):
    try:
        with open(log_file_path, "a", encoding="utf-8") as f:
            for line in iter(pipe.readline, ''):
                if line:
                    stripped_line = line.strip()
                    logger.info(f"[BioGAIP] {stripped_line}")
                    f.write(line)
                    f.flush()
    except Exception as e:
        logger.error(f"Error reading process logs: {e}")
    finally:
        if pipe:
            pipe.close()

def main():
    st.set_page_config(page_title="BioGAIP Easy Launcher", page_icon="🚀", layout="wide")
    
    st.markdown("""
        <style>
        [data-testid="stHeader"] {display: none;}
        .stDeployButton {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

    st.title("🚀 BioGAIP Easy Launcher")
    st.markdown("A lightweight tool to launch pre-configured BioGAIP instances locally.")

    if 'license_accepted' not in st.session_state:
        st.session_state.license_accepted = False

    if not st.session_state.license_accepted:
        st.warning("📜 AGPL-3 License Agreement")
        st.markdown("""
        **AGPL-3.0 License**
        BioGAIP, bioAG, and bioWorker are licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
        
        Copyright (C) 2025 BioGAIP Team.

        This program is free software: you can redistribute it and/or modify
        it under the terms of the GNU Affero General Public License as
        published by the Free Software Foundation, either version 3 of the
        License, or (at your option) any later version.

        **THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.**
        """)
        agree = st.checkbox("I accept the terms of the AGPL-3.0 License and understand there is no warranty or liability.")
        if st.button("Continue") and agree:
            st.session_state.license_accepted = True
            st.rerun()
        st.stop()
        
    if 'step' not in st.session_state:
        st.session_state.step = 1
        st.session_state.params = {}
        st.session_state.config_method = None
        st.session_state.random_key = '_' + ''.join(random.choices(string.ascii_letters + string.digits, k=6))
        
    biogaip_exe = get_biogaip_exe()

    if st.session_state.step == 1:
        st.header("Step 1: Environment Check")
        with st.expander("Details", expanded=True):
            st.write("Checking for BioGAIP environment executable...")
            if biogaip_exe:
                try:
                    res = subprocess.run([biogaip_exe, '-h'], capture_output=True, text=True)
                    st.success(f"✅ Executable found: `{biogaip_exe}`")
                except Exception as e:
                    logger.warning(f"Test execution failed: {e}")
                    st.warning(f"⚠️ Executable found but test execution failed: {e}")
            else:
                st.error("❌ `biogaip` executable not found in Scripts or bin directories. Please ensure it is correctly installed via pip.")
                st.stop()

        with st.expander("Advanced Options", expanded=True):
            force_mode = st.checkbox("Force Mode (allow multiple instances)", value=st.session_state.get('force_mode', False))
            allow_network = st.checkbox("Allow Connections from the Local Network", value=st.session_state.get('allow_network_visit', False))
            st.session_state.force_mode = force_mode
            st.session_state.allow_network_visit = allow_network

        if st.button("Next ➡️"):
            st.session_state.step = 2
            st.rerun()

    elif st.session_state.step == 2:
        st.header("Step 2: Parameter Configuration")
        if st.session_state.config_method is None:
            st.subheader("Choose Your LLM API Configuration Method")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 📤 Upload File\n**Pros:**\n- Quick and straightforward\n- Allow custom configurations")
                if st.button("Upload File", key="select_upload"):
                    st.session_state.config_method = "Upload File"
                    st.rerun()
            with col2:
                st.markdown("### ✏️ Online Edit\n**Pros:**\n- Edit directly in browser\n- Easy quick adjustments")
                if st.button("Select Online Edit", key="select_online"):
                    st.session_state.config_method = "Online Edit"
                    st.rerun()
        else:
            st.subheader(f"Configuration: {st.session_state.config_method}")
            
            home_dir = os.path.expanduser("~")
            default_cache_path = os.path.join(home_dir, "bioGen", "cache")

            conf_file_buffer = None
            m1_name = m1_base = m1_key = m4_name = m4_base = m4_key = ""
            use_sep_api = False

            if st.session_state.config_method == "Upload File":
                conf_file_buffer = st.file_uploader("Configure File (required)", type=["yaml", "yml"])
            else:
                st.markdown("#### Primary LLM Configuration (Model 1)")
                m1_name = st.text_input("Model Name", value="gpt-4o")
                m1_base = st.text_input("Base URL", value="https://api.openai.com/v1")
                m1_key = st.text_input("API Key", type="password")

                with st.expander("Advanced Model Settings"):
                    max_tokens = st.number_input("Max Tokens", value=131072, step=1024)
                    family = st.text_input("Model Family", value="gpt-4o")
                    
                    c1, c2, c3 = st.columns(3)
                    vision = c1.checkbox("Vision Support", value=False)
                    func_call = c2.checkbox("Function Calling", value=True)
                    json_out = c3.checkbox("JSON Output", value=False)
                    
                    c4, c5, _ = st.columns(3)
                    struct_out = c4.checkbox("Structured Output", value=True)
                    multi_sys = c5.checkbox("Multiple System Messages", value=True)

                st.markdown("#### Advanced Summary Configuration")
                use_sep_api = st.checkbox("Use separate summary API (assign to Model 4)")
                if use_sep_api:
                    st.markdown("##### Summary LLM Configuration (Model 4)")
                    m4_name = st.text_input("Summary Model Name", value="gpt-4o-mini")
                    m4_base = st.text_input("Summary Base URL", value="https://api.openai.com/v1")
                    m4_key = st.text_input("Summary API Key", type="password")
                    
                    with st.expander("Advanced Summary Model Settings"):
                        m4_max_tokens = st.number_input("Summary Max Tokens", value=131072, step=1024)
                        m4_family = st.text_input("Summary Model Family", value="gpt-4o-mini")
                        
                        sc1, sc2, sc3 = st.columns(3)
                        m4_vision = sc1.checkbox("Summary Vision Support", value=False)
                        m4_func_call = sc2.checkbox("Summary Function Calling", value=True)
                        m4_json_out = sc3.checkbox("Summary JSON Output", value=False)
                        
                        sc4, sc5, _ = st.columns(3)
                        m4_struct_out = sc4.checkbox("Summary Structured Output", value=True)
                        m4_multi_sys = sc5.checkbox("Summary Multiple System Messages", value=True)

            with st.expander("Advanced Database & Cache Options", expanded=False):
                session_id = st.text_input("Session ID (optional)", help="Leave blank to generate a random ID automatically")
                conda_meta = st.text_input("Conda Meta DB (optional)")
                workflow = st.text_input("Workflow DB (optional)")
                user_ext = st.text_input("User Ext Resources (Directory with pdf, docx, txt, etc. Optional)")
                cache = st.text_input("Cache Dir", value=default_cache_path)
                res_cache = st.text_input("Resource Cache Dir", value=default_cache_path)
                proxy = st.text_input("HTTP Proxy (optional)", help="e.g. http://127.0.0.1:7890")

            st.markdown("#### App Settings")
            col_u1, col_u2, col_u3 = st.columns(3)
            user_name = col_u1.text_input("User Name", value="admin")
            user_password = col_u2.text_input("Password", value="admin", type="password")
            bioag_port = col_u3.number_input("Frontend Port", min_value=1024, max_value=65535, value=8501)
            
            cols = st.columns(3)
            back_to_selection = cols[0].button("⬅️ Back to Selection")
            back_to_step1 = cols[1].button("⬅️ Back to Step 1")
            next_button = cols[2].button("Next ➡️")

            if back_to_selection:
                st.session_state.config_method = None
                st.rerun()
            if back_to_step1:
                st.session_state.step = 1
                st.session_state.config_method = None
                st.rerun()

            if next_button:
                logger.info("Generating configuration file...")
                tmp_dir = os.path.join(cache, "config_tmp", st.session_state.random_key)
                os.makedirs(tmp_dir, exist_ok=True)
                
                _TEMP_PATHS.add(tmp_dir)

                config_output_path = os.path.join(tmp_dir, "system_config.yaml")

                if st.session_state.config_method == "Upload File":
                    if conf_file_buffer is None:
                        st.error("Please upload a configuration file.")
                        st.stop()
                    with open(config_output_path, "wb") as f:
                        f.write(conf_file_buffer.getbuffer())
                else:
                    template_path = 'assets/system_config.yaml'
                    if not os.path.exists(template_path):
                        template_path = 'resources/assets/system_config.yaml'

                    try:
                        with open(template_path, 'r', encoding='utf-8') as f:
                            config_yaml = yaml.safe_load(f)
                    except Exception as e:
                        logger.warning(f"Could not load template yaml: {e}. Generating from scratch.")
                        config_yaml = {"model_client": {"model_client1": {"class": "OpenAIChatCompletionClient", "kwargs": {}}}}

                    if 'model_client' not in config_yaml:
                        config_yaml['model_client'] = {}
                    
                    base_client = config_yaml['model_client'].get('model_client1', {}).copy()
                    if 'kwargs' not in base_client: base_client['kwargs'] = {}
                    if 'class' not in base_client: base_client['class'] = "OpenAIChatCompletionClient"
                    
                    base_client['kwargs']['model'] = m1_name
                    base_client['kwargs']['base_url'] = m1_base
                    base_client['kwargs']['api_key'] = m1_key
                    base_client['kwargs']['max_tokens'] = max_tokens
                    base_client['kwargs']['model_info'] = {
                        "vision": vision,
                        "function_calling": func_call,
                        "json_output": json_out,
                        "family": family,
                        "structured_output": struct_out,
                        "multiple_system_messages": multi_sys
                    }

                    config_yaml['model_client']['model_client1'] = copy.deepcopy(base_client)
                    config_yaml['model_client']['model_client2'] = copy.deepcopy(base_client)
                    config_yaml['model_client']['model_client3'] = copy.deepcopy(base_client)

                    if use_sep_api:
                        summary_client = copy.deepcopy(base_client)
                        summary_client['kwargs']['model'] = m4_name
                        summary_client['kwargs']['base_url'] = m4_base
                        summary_client['kwargs']['api_key'] = m4_key
                        summary_client['kwargs']['max_tokens'] = m4_max_tokens
                        summary_client['kwargs']['model_info'] = {
                            "vision": m4_vision,
                            "function_calling": m4_func_call,
                            "json_output": m4_json_out,
                            "family": m4_family,
                            "structured_output": m4_struct_out,
                            "multiple_system_messages": m4_multi_sys
                        }
                        config_yaml['model_client']['model_client4'] = summary_client
                    else:
                        config_yaml['model_client']['model_client4'] = copy.deepcopy(base_client)

                    with open(config_output_path, 'w', encoding='utf-8') as f:
                        yaml.safe_dump(config_yaml, f, allow_unicode=True)

                st.session_state.params = {
                    "session_id": session_id,
                    "conf_file": config_output_path,
                    "conda_meta": conda_meta, "workflow": workflow, "user_ext": user_ext,
                    "cache": cache, "res_cache": res_cache, "proxy": proxy,
                    "user_name": user_name, "user_password": user_password,
                    "bioag_port": bioag_port
                }
                st.session_state.step = 3
                st.rerun()

    elif st.session_state.step == 3:
        st.header("Step 3: Execute")
        params = st.session_state.params
        port = params['bioag_port']
        need_refresh = False
        
        with st.expander("Parameters Summary", expanded=False):
            st.json(params)

        is_running = ('bypass_process' in st.session_state and 
                      st.session_state.bypass_process is not None and 
                      st.session_state.bypass_process.poll() is None)
        
        has_failed = ('bypass_process' in st.session_state and 
                      st.session_state.bypass_process is not None and 
                      st.session_state.bypass_process.poll() is not None)

        if is_running:
            st.success(f"✅ The environment is currently running on port {port}!")
            host = "0.0.0.0" if st.session_state.allow_network_visit else "127.0.0.1"
            st.markdown(f"**Application URL:** [http://{host}:{port}](http://{host}:{port})")
        elif has_failed:
            exit_code = st.session_state.bypass_process.returncode
            st.error(f"❌ Process failed to start or terminated unexpectedly (Exit code: {exit_code}). Please check the runtime logs below.")

        log_file = st.session_state.get('biogaip_log_file')
        if log_file and os.path.exists(log_file):
            with st.expander("📝 Runtime Logs", expanded=True):
                col_l1, col_l2 = st.columns([1, 4])
                if col_l1.button("🔄 Refresh Logs", use_container_width=True):
                    st.rerun()
                
                auto_refresh = col_l2.checkbox("Auto-Refresh (Auto-updates every 1.5 seconds)")
                if auto_refresh and is_running:
                    need_refresh = True

                try:
                    with open(log_file, "r", encoding="utf-8") as lf:
                        lines = lf.readlines()
                        log_content = "".join(lines[-1000:])
                    st.code(log_content, language="bash")
                except Exception as e:
                    st.error(f"Error reading log file: {e}")

        st.markdown("---")
        cols = st.columns(3)
        if cols[0].button("⬅️ Back"):
            st.session_state.step = 2
            st.rerun()
            
        if cols[1].button("🛑 Stop / Clear Status", disabled=(st.session_state.get('bypass_process') is None)):
            stop_current_session()
            st.success("Environment stopped and status cleared.")
            st.rerun()

        if cols[2].button("▶️ Run", disabled=is_running):
            logger.info(f"Preparing to run BioGAIP on port {port}...")
            if is_port_occupied(port):
                if st.session_state.get('force_mode', False):
                    st.warning(f"Port {port} is occupied, but Force Mode is enabled. Execution will proceed.")
                    logger.warning(f"Port {port} occupied, proceeding due to Force Mode.")
                else:
                    st.error(f"Port {port} is already occupied. Stop the existing process or enable Force Mode in Step 1.")
                    logger.error(f"Execution aborted: Port {port} is occupied.")
                    st.stop()

            env = copy.deepcopy(os.environ)
            
            exe_dir = os.path.dirname(biogaip_exe)
            current_path = env.get("PATH", "")
            if exe_dir not in current_path:
                env["PATH"] = exe_dir + os.pathsep + current_path

            sid = params.get("session_id", "").strip()
            if not sid:
                sid = random.randbytes(3).hex()
            persist_dir = os.path.join(params["cache"], f"user_sessions_{sid}")

            env["PERSIST_DIR"] = persist_dir
            env["SYSTEM_CONFIG_YAML_PATH"] = params["conf_file"]
            env["BIOAG_PORT"] = str(port)
            env["BIOGEN_BYPASSMODE"] = "true"
            env["TQDM_DISABLE"] = "1"
            env["COOKIE_PASSWORD"] = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

            if params["proxy"]:
                env["http_proxy"] = params["proxy"]
                env["https_proxy"] = params["proxy"]
            if params["user_name"] and params["user_password"]:
                env["APP_USER"] = f"{params['user_name']}:{params['user_password']}"
                
            if params["conda_meta"]: env["CONDA_META_DATABASE"] = params["conda_meta"]
            if params["workflow"]: env["WORKFLOW_DATABASE"] = params["workflow"]
            if params["user_ext"]: env["USER_EXT_DATABASE"] = params["user_ext"]
            if params["cache"]: env["WORK_DIR"] = params["cache"]
            
            if st.session_state.allow_network_visit:
                env["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
            else:
                env["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"

            log_dir = os.path.join(params["cache"], "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file_path = os.path.join(log_dir, f"run_{st.session_state.random_key}.log")
            st.session_state.biogaip_log_file = log_file_path

            try:
                with open(log_file_path, "w", encoding="utf-8") as lf:
                    lf.write("="*60 + "\n")
                    lf.write("🚀 BioGAIP Process Starting...\n")
                    lf.write("="*60 + "\n")
                    lf.write(f"▶ COMMAND:\n  {biogaip_exe}\n\n")
                    lf.write("▶ INJECTED ENVIRONMENT VARIABLES:\n")
                    
                    env_keys_to_print = [
                        "http_proxy", "https_proxy", "APP_USER", "CONDA_META_DATABASE", 
                        "WORKFLOW_DATABASE", "USER_EXT_DATABASE", "WORK_DIR", 
                        "BIOAG_PORT", "BIOGEN_BYPASSMODE", "SYSTEM_CONFIG_YAML_PATH", 
                        "PERSIST_DIR", "STREAMLIT_SERVER_ADDRESS"
                    ]
                    for k in env_keys_to_print:
                        if k in env:
                            val = env[k]
                            if k == "APP_USER" and ":" in val:
                                val = val.split(':')[0] + ":******"
                            lf.write(f"  {k} = {val}\n")
                    lf.write("="*60 + "\n\n")
            except Exception as e:
                logger.error(f"Failed to write initial log headers: {e}")

            try:
                logger.info(f"Launching subprocess: {biogaip_exe}")
                
                popen_kwargs = {
                    "env": env,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "text": True,
                    "bufsize": 1
                }
                
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    popen_kwargs["start_new_session"] = True

                process = subprocess.Popen(
                    [biogaip_exe] + ["--port", str(port)], 
                    **popen_kwargs
                )
                
                st.session_state.bypass_process = process
                _ACTIVE_PROCESSES.add(process)
                
                log_thread = threading.Thread(target=stream_process_logs, args=(process.stdout, log_file_path), daemon=True)
                log_thread.start()

                time.sleep(2)
                
                if process.poll() is None:
                    logger.info(f"BioGAIP instance successfully launched with PID {process.pid}")
                else:
                    logger.error(f"Process terminated unexpectedly with exit code {process.returncode}")
                
                st.rerun()

            except Exception as e:
                st.error(f"Error launching BioGAIP executable: {e}")
                logger.exception("Exception occurred during process launch")

        if need_refresh:
            time.sleep(1.5)
            st.rerun()

if __name__ == "__main__":
    main()