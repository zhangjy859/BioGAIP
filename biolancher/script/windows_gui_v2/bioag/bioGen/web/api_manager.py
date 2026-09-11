import os
import sys
import time
import requests
import asyncio
import subprocess
import threading
from queue import Queue, Empty
import re
import streamlit as st

from bioGen.biogen import *

def shutdown_server(host=None, api_key=None):
    if not api_key or not host:
        raise ValueError("API key is required")
    response = requests.post(f"{host}/shutdown", headers={"x-api-key": api_key})
    response.raise_for_status()
    return response.json()

def get_project_status(project_id, API_URL=None, API_KEY=None):
    if not project_id: return "No Project ID"
    try:
        response = requests.get(f"{API_URL}/status/project/{project_id}", headers={"x-api-key": API_KEY})
        if response.status_code == 200:
            data = response.json()
            import json
            if isinstance(data, str): data = json.loads(data)
            return data
        return f"Error: {response.status_code}"
    except Exception as e:
        return f"Exception: {str(e)}"

#def check_api(session_state, remote_tool_loaded, logger, reset_project_id=False):
#    try:
#        if ('project_id' not in session_state and os.getenv('PROJECT_ID') is None) or reset_project_id:
#            result = asyncio.run(execute_shell_command_via_api(command=''))
#            session_state['project_id'] = os.environ["PROJECT_ID"]
#            if remote_tool_loaded:
#                try:
#                    _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ['PROJECT_ID'], api_base_url=os.environ['API_URL'], api_key=os.environ['API_KEY'])
#                    logger.info(f"set_remote_tools: {_}")
#                except Exception as e:
#                    logger.info(f'biogen error: {e}')
#        else:
#            result = asyncio.run(execute_shell_command_via_api(command='echo ok'))
#        return bool(result)
#    except Exception as e:
#        st.error(f"API check failed: {str(e)}")
#        raise e

def check_api(session_state, remote_tool_loaded, logger, reset_project_id=False, recovery=False):
    try:
        if ('project_id' not in session_state and os.getenv('PROJECT_ID') is None) or reset_project_id:
            result = asyncio.run(execute_shell_command_via_api(command=''))
            session_state['project_id'] = os.environ["PROJECT_ID"]
            if remote_tool_loaded:
                try:
                    _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ['PROJECT_ID'], api_base_url=os.environ['API_URL'], api_key=os.environ['API_KEY'])
                    logger.info(f"set_remote_tools: {_}")
                except Exception as e:
                    logger.info(f'biogen error: {e}')
            return bool(result)
        else:
            project_id = session_state.get('project_id') or os.getenv('PROJECT_ID')
            status = get_project_status(project_id, os.getenv('API_URL'), os.getenv('API_KEY'))
            if not isinstance(status, dict):
                if recovery:
                    return check_api(session_state, remote_tool_loaded, logger, reset_project_id=True, recovery=False)
                return False
            return True
    except Exception as e:
        st.error(f"API check failed: {str(e)}")
        raise e

def api_set2(server_ip, username, port, ssh_password, api_key, read_only_dir='', read_write_dir='', work_dir='', allow_raw='', temp_dir=None, bioworker_port=None, use_sandbox_type=None, max_task=1, web_admin=False):
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
    if use_sandbox_type: cmd += ['--use_sandbox', use_sandbox_type]
    if bioworker_port: cmd += ['--bioworker_port', str(bioworker_port)]
    if temp_dir and temp_dir != '': cmd += ['--temp_dir', temp_dir]
    cmd += ['--max_task', str(max_task)]
    cmd += ['--web_admin', str(web_admin)]

    logger = logging.getLogger(__name__)
    try:
        ## deep copy cmd to logger_cmd to avoid modifying the original cmd
        logger_cmd = cmd.copy()
        ## rm password and api_key from logger_cmd for security
        if len(logger_cmd) > 6:
            logger_cmd[4] = logger_cmd[4][0:2] + '_REDACTED***'
            logger_cmd[5] = logger_cmd[5][0:2] + '_REDACTED***'
            logger_cmd[6] = logger_cmd[6][0:2] + '_REDACTED***'
        logger.info(f"Executing command: {' '.join(logger_cmd)}")
    except Exception as e:
        logger.error(f"Error logging executing command: {e}")

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    output, err_output = "", ""
    stdout_queue, stderr_queue = Queue(), Queue()

    def read_stream(stream, queue):
        for line in iter(stream.readline, b''): queue.put(line.decode('utf-8', errors='replace'))
        queue.put(None)

    threading.Thread(target=read_stream, args=(process.stdout, stdout_queue), daemon=True).start()
    threading.Thread(target=read_stream, args=(process.stderr, stderr_queue), daemon=True).start()

    success = False
    progress_bar = st.progress(0, text="Starting API setup...")

    while True:
        try:
            while True:
                line = stdout_queue.get_nowait()
                if line is None: break
                if line:
                    output += line
                    match = re.match(r'^%(\d+)%\s*(.*)$', line.strip())
                    if match:
                        progress_bar.progress(int(match.group(1)) / 100.0, text=match.group(2))
                        time.sleep(0.1)
                    if "Successfully started bioGen API server" in line:
                        os.environ['API_URL'] = f"http://{server_ip}:{bioworker_port}"
                        os.environ['API_KEY'] = api_key
                        st.session_state.api_process = process
                        st.info(f"API setup completed. View progression at {os.environ.get('API_URL')}")
                        success = True
        except Empty: pass

        try:
            while True:
                err_line = stderr_queue.get_nowait()
                if err_line is None: break
                if err_line:
                    err_output += err_line
                    st.error(f"Error output: {err_line.rstrip()}")
        except Empty: pass

        if success:
            progress_bar.progress(1.0, text="API setup completed")
            time.sleep(0.1)
            return success, output, err_output

        if process.poll() is not None:
            if not success:
                progress_bar.progress(0, text="API setup failed")
                return False, output, err_output
        time.sleep(0.01)

def pair_api_set(pair_code):
    pass

def check_model():
    model_dir = os.path.expanduser("~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/")
    tar_file_path = os.path.join(model_dir, "onnx.tar.gz")
    url = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
    if os.path.exists(model_dir) and os.path.exists(tar_file_path): return True
    st.markdown("The Embedding model file (required by RAG) is missing. It needs to be downloaded and extracted.")
    if st.button("Download and Extract"):
        try:
            os.makedirs(model_dir, exist_ok=True)
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            progress_bar = st.progress(0)
            downloaded = 0
            with open(tar_file_path, "wb") as f:
                for data in response.iter_content(1024):
                    downloaded += len(data)
                    f.write(data)
                    if total_size > 0: progress_bar.progress(downloaded / total_size)
            import tarfile
            with tarfile.open(tar_file_path) as tar: tar.extractall(path=model_dir)
            st.success("Extraction complete!")
            return True
        except Exception as e:
            st.markdown(f"An error occurred: {str(e)}")
            return False
    return True