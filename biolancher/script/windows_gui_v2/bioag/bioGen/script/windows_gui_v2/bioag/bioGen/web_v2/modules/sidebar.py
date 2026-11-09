import os
import time
import zipfile
import secrets
import requests
import streamlit as st
from bioGen.web_v2.api_manager import shutdown_server, get_project_status, check_api, api_set2, check_model
from bioGen.web_v2.utils import force_kill_process
from modules.utils import get_file_prefix, create_workspace_zip

@st.dialog("Reset Session Warning")
def reset_session_confirm(persist_dir, storage, logger):
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
            pid_file = os.path.join(persist_dir, f"{get_file_prefix()}.process_pid")
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

@st.dialog("📥 Import Workspace")
def import_workspace_dialog(persist_dir, cookies):
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

def render_sidebar(persist_dir, storage, logger, cookies, version_data):
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
            
    with col_s2:
        if st.button("Reset", width="stretch"):
            st.session_state.show_reset_dialog = True

    if st.session_state.get("show_reset_dialog", False):
        reset_session_confirm(persist_dir, storage, logger)

    st.sidebar.divider()
    st.sidebar.subheader("📦 Workspace Manager")

    st.sidebar.download_button(
        label="📤 Export Workspace",
        data=create_workspace_zip(persist_dir),
        file_name=f"biogaip_workspace_{st.session_state.get('username', 'export')}.zip",
        mime="application/zip",
        width="stretch"
    )

    if st.sidebar.button("📥 Import Workspace", width="stretch"): 
        st.session_state.show_import_dialog = True

    if st.session_state.get("show_import_dialog", False):
        import_workspace_dialog(persist_dir, cookies)

    _render_api_setup(logger)
    _render_dashboard()

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

def _render_api_setup(logger):
    remote_tool_loaded = globals().get('remote_tool_loaded', True)
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

def _render_dashboard():
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