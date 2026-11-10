import os
import sys
import time
import random
import string
import subprocess
import shutil
import re
import copy
import threading
import atexit
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from constants import micromamba_path, biogen_env, script_dir
from utils import get_all_descendants, is_port_occupied

def start_bypass(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, enable_gpu, output_queue, user_name="admin", user_password="admin", gemini_mode=False, port=8501, allow_network=False, local_storage = 'File System (Json)'):
    if front_ui != "streamlit":
        output_queue.put("Error: In Bypass mode, only streamlit is supported. Chainlit and CLI modes are disabled.")
        output_queue.put("DONE")
        return
        
    output_queue.put(("STATUS", 1, "RUNNING", "Preparing Bypass Environment..."))
    env = copy.deepcopy(os.environ)
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    if gemini_mode: env["SKIP_MODEL_CONTEXT"] = "true"
    if user_name and user_password: env["APP_USER"] = f"{user_name}:{user_password}" 
    if conda_meta: env["CONDA_META_DATABASE"] = conda_meta
    if workflow: env["WORKFLOW_DATABASE"] = workflow
    if user_ext: env["USER_EXT_DATABASE"] = user_ext
    if cache: env["WORK_DIR"] = cache
    if port: env["BIOAG_PORT"] = str(port)
    if local_storage == 'SQLite': env["USE_SQLITE"] = "true"
        
    env["PYTHONPATH"] = os.path.join(script_dir, 'bioag')
    env["BIOGEN_BYPASSMODE"] = "true"
    env["TQDM_DISABLE"] = "1"
    env["COOKIE_PASSWORD"] = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    if os.path.exists(os.path.join(cache, 'user_sessions'+st.session_state.random_key, f"{user_name}.json")):
        os.remove(os.path.join(cache, 'user_sessions'+st.session_state.random_key, f"{user_name}.json"))
        
    if not st.session_state.get('random_id', None):
        st.session_state.random_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        
    config_base = os.path.join(script_dir, 'config')
    os.makedirs(config_base, exist_ok=True)
    target_config_dir = os.path.join(config_base, f"bioag_temp_{st.session_state.random_id}")
    source_config_dir = os.path.join(script_dir, 'bioag', 'bioGen', 'config')
    
    if os.path.exists(target_config_dir): shutil.rmtree(target_config_dir)
    shutil.copytree(source_config_dir, target_config_dir)
    
    if configure:
        os.environ['SYSTEM_CONFIG_PATH'] = target_config_dir
        env['SYSTEM_CONFIG_PATH'] = target_config_dir
        shutil.copy(configure, os.path.join(target_config_dir, 'system_config.yaml'))

    streamlit_path = os.path.join(script_dir, 'bioag', 'bioGen', 'web', 'app_streamlit1.py')
    if not os.path.exists(streamlit_path):
        streamlit_path = os.path.join(script_dir, 'app', 'bioag', 'bioGen', 'web', 'app_streamlit.py')
    if not os.path.exists(streamlit_path):
        output_queue.put("Error: Streamlit app script not found.")
        output_queue.put("DONE")
        return
        
    cmd = [micromamba_path, 'run', '-p', biogen_env, 'streamlit', 'run', '--server.headless=true', streamlit_path, '--server.port', str(port)]
    if not allow_network: cmd += ['--server.address=127.0.0.1']
    
    log_file_path = None
    if cache:
        log_dir = os.path.join(cache, 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{user_name}_bioag_{st.session_state.random_id}.log")
        
    init_complete = threading.Event()

    def read_pipe(pipe, queue, is_stderr, pid, event, log_file_path=None):
        reported = False
        try: 
            for line in iter(pipe.readline, ''):
                if line:
                    sys.stderr.write(f"[PID {pid}] {'[ERR]' if is_stderr else '[OUT]'} {line}")
                    stripped = line.strip()
                    queue.put(("ERR: " if is_stderr else "") + stripped)
                    if not reported and "http" in stripped.lower():
                        event.set()
                        reported = True
                    if log_file_path:
                        with open(log_file_path, 'a') as f:
                            f.write(f"{line}")
        except Exception as e: sys.stderr.write(f"Error reading pipe for PID {pid}: {e}\n")
        pipe.close()

    output_queue.put(("STATUS", 1, "SUCCESS", "Environment Prepared"))
    output_queue.put(("STATUS", 2, "RUNNING", "Launching Subprocess..."))

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env, cwd=script_dir)
        pid = process.pid
        st.session_state.bypass_process = process
        st.session_state.bypass_config_dir = target_config_dir
        
        output_queue.put("Process starting up...")
        output_queue.put(("STATUS", 2, "SUCCESS", f"Subprocess Launched (PID: {pid})"))
        output_queue.put(("STATUS", 3, "RUNNING", "Waiting for Network Initialization..."))

        stdout_thread = threading.Thread(target=read_pipe, args=(process.stdout, output_queue, False, pid, init_complete, log_file_path))
        stderr_thread = threading.Thread(target=read_pipe, args=(process.stderr, output_queue, True, pid, init_complete, log_file_path))
        add_script_run_ctx(stdout_thread)
        add_script_run_ctx(stderr_thread)
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        if not init_complete.wait(timeout=120):
            if process.poll() is not None:
                output_queue.put(("STATUS", 3, "ERROR", f"Process Terminated (Exit: {process.returncode})"))
                output_queue.put(f"Error: Process terminated unexpectedly. Exit code: {process.returncode}")
            else:
                output_queue.put(("STATUS", 3, "ERROR", f"Initialization timeout reached for PID {pid}."))
            if 'bypass_config_dir' in st.session_state:
                shutil.rmtree(st.session_state.bypass_config_dir)
                del st.session_state.bypass_config_dir
            output_queue.put(f"SUCCESS:False")
            output_queue.put("DONE")
            return

        descendants = get_all_descendants(pid)
        actual_pid = None
        find_start = time.time()
        while time.time() - find_start < 10:
            try:
                cmd_net = f'netstat -ano | findstr :{port}'
                output = subprocess.check_output(cmd_net, shell=True).decode('utf-8', errors='ignore')
                for line in output.splitlines():
                    if 'LISTENING' in line:
                        parts = re.split(r'\s+', line.strip())
                        if parts and parts[-1].isdigit():
                            listen_pid = int(parts[-1])
                            if listen_pid in descendants:
                                task_cmd = f'tasklist /fi "PID eq {listen_pid}"'
                                task_output = subprocess.check_output(task_cmd, shell=True).decode('utf-8', errors='ignore')
                                if 'python.exe' in task_output.lower():
                                    actual_pid = listen_pid
                                    break
                if actual_pid: break
            except Exception as e: pass
            time.sleep(1)

        output_queue.put(f"Initialization:{actual_pid or pid}")
        output_queue.put(("STATUS", 3, "SUCCESS", "Local Server is Active"))
        output_queue.put(f"SUCCESS:True")
        output_queue.put("DONE")
        time.sleep(9) 
        return 

    except Exception as e:
        output_queue.put(("STATUS", 2, "ERROR", "Process Launch Failed"))
        output_queue.put(f"Error starting process: {e}")
        if 'bypass_config_dir' in st.session_state:
            shutil.rmtree(st.session_state.bypass_config_dir)
            del st.session_state.bypass_config_dir
        output_queue.put(f"SUCCESS:False")
        output_queue.put("DONE")
        return

def stop_bypass_task(output_queue):
    output_queue.put(("STATUS", 1, "RUNNING", "Locating Bypass Process..."))
    if 'bypass_process' in st.session_state and st.session_state.bypass_process:
        process = st.session_state.bypass_process
        output_queue.put(("STATUS", 1, "SUCCESS", f"Process Found (PID {process.pid})"))

        output_queue.put(("STATUS", 2, "RUNNING", "Terminating Process..."))
        process.terminate()
        process.wait()
        output_queue.put(("STATUS", 2, "SUCCESS", "Process Terminated"))

        output_queue.put(("STATUS", 3, "RUNNING", "Cleaning Up Configurations..."))
        if 'bypass_config_dir' in st.session_state and os.path.exists(st.session_state.bypass_config_dir):
            shutil.rmtree(st.session_state.bypass_config_dir)
            del st.session_state.bypass_config_dir
        del st.session_state.bypass_process
        output_queue.put(("STATUS", 3, "SUCCESS", "Cleanup Complete"))
    else:
        output_queue.put(("STATUS", 1, "SKIPPED", "No Running Process Found"))
        output_queue.put(("STATUS", 2, "SKIPPED", "Termination Skipped"))
        output_queue.put(("STATUS", 3, "SKIPPED", "Cleanup Skipped"))
    output_queue.put("DONE")

def cleanup_bypass():
    if 'bypass_process' in st.session_state and st.session_state.bypass_process:
        st.session_state.bypass_process.terminate()
        st.session_state.bypass_process.wait()
    if 'bypass_config_dir' in st.session_state and os.path.exists(st.session_state.bypass_config_dir):
        shutil.rmtree(st.session_state.bypass_config_dir)
atexit.register(cleanup_bypass)