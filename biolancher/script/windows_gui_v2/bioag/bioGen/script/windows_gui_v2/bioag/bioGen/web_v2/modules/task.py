import os
import time
import json
import threading
import multiprocessing
import platform
import streamlit as st
import bioGen.context_summary as bg_summary
from bioGen.web_v2.utils import force_kill_process, read_uploaded_file
from bioGen.web_v2.api_manager import get_project_status
from bioGen.web_v2.agent_processor import create_team, process_task
from bioGen.biogen import *
from modules.utils import get_file_prefix, check_team_pid_running

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

def handle_task_execution(persist_dir, storage, logger):
    if 'last_uploaded_files' not in st.session_state: st.session_state.last_uploaded_files = set()
    if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
    st.session_state.init_messaged = False

    placeholder_text = "Type your response here..." if st.session_state.get('waiting_for_user_input', False) else "Message the agents..."
    if st.session_state.get('processing', False) and not st.session_state.get('waiting_for_user_input', False): placeholder_text = "Task in progress. Stop the task to input text..."

    user_prompt_json = os.path.join(persist_dir, f"{get_file_prefix()}_input.ujson")
    chat_file_types = ['txt', 'md', 'html', 'pdf', 'htm', 'py', 'js', 'sh', 'docx', 'xlsx', 'pptx', 'java', 'c', 'cpp', 'h', 'rb', 'pl', 'php', 'go', 'rs', 'kt', 'swift', 'r', 'm', 'lua', 'cs', 'ts', 'scala', 'groovy', 'perl', 'bat', 'cmd', 'ps1', 'pm', 'vb', 'f', 'f90', 'jl', 'hs', 'Rmd', 'ipynb']

    message = None
    uploaded_files = []

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
                            st.session_state.user_confirmed_summary = False
                            st.session_state.user_required_summary = True
                            st.session_state.team_summary_file = os.path.join(persist_dir, f"{get_file_prefix()}.summary_team")
                            st.session_state.team_exit_file = os.path.join(persist_dir, f"{get_file_prefix()}.team")
                            st.session_state.show_refresh_dialog = True
                    
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

    _process_task_engine(persist_dir, storage, logger, user_prompt_json)
    _poll_logs_engine(storage)

def _process_task_engine(persist_dir, storage, logger, user_prompt_json):
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
            st.session_state.max_content = globals().get('sys_config', {}).get('max_content', 1000)
            st.session_state.max_summary_content = globals().get('sys_config', {}).get('max_summary_content', 10000)
            
            if os.path.exists(team_summary_file):
                os.remove(team_summary_file)
                st.session_state.is_team_summary_active = True
                team_summary = True
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
                    ag_file = os.path.join(persist_dir, f"{get_file_prefix()}.agjson")
                    if os.path.exists(ag_file): os.remove(ag_file)
                    
                    with st.spinner("Analyzing context and generating strategic summary..."):
                        user_prompt_history = storage.get_user_prompt_history(st.session_state.username, file_path=user_prompt_json)
                        session_file_for_summary = storage.export_session_to_json(st.session_state.username, st.session_state)
                        
                        _model = globals().get('content_summary_model', None)
                        content_summary = bg_summary.run_summary(session_file_for_summary, _model, st.session_state.max_summary_content, user_prompt_history)
                        
                        st.session_state.chat_summary_message = f"==============User Orginal task============\n{str(user_prompt_history)}\nCurrent Processing Summary:\n{content_summary}\n"
                        st.session_state.content_summary_raw = content_summary
                        st.session_state.user_prompt_history_raw = str(user_prompt_history)

            if team_summary and not st.session_state.get('finish_summary', False):
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
                    sucessfulExecutate_reward = globals().get('sys_config', {}).get('sucessfulExecutate_reward', 10)
                    if platform.system().lower() != 'windows':
                        process_p = multiprocessing.Process(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, os.getpid()), daemon=True)
                        process_p.start()
                        with open(pid_file, 'w') as f: f.write(str(process_p.pid))
                    else:
                        process_p = threading.Thread(target=process_task, args=(user_message, st.session_state.log_file, st.session_state.team, st.session_state.stop_team, st.session_state.force_stop, st.session_state.agent_status_file, st.session_state.team_exit_file, st.session_state.team_summary_file, st.session_state.max_content, st.session_state.get('load_history', True), sucessfulExecutate_reward, storage, logger, None), daemon=True)
                        process_p.start()
                        with open(pid_file, 'w') as f: f.write(str(os.getpid()))
                    if 'init_processing' in st.session_state: st.session_state.init_processing = False
                    
                st.rerun()

def _poll_logs_engine(storage):
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