import os
import zipfile
import io
import streamlit as st

def get_file_prefix():
    pid = st.session_state.get('project_id', 'default')
    return f"{st.session_state.get('username', 'user')}_{pid}"

def check_team_pid_running(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f: 
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    return False

def create_workspace_zip(persist_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(persist_dir):
            for file in files:
                file_path = os.path.join(root, file)
                z.write(file_path, os.path.relpath(file_path, persist_dir))
    buf.seek(0)
    return buf