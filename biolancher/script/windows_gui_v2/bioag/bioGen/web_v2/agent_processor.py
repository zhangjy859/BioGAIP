import os
import sys
import json
import time
import asyncio
import random
import threading
import platform
import openai
from openai import RateLimitError, BadRequestError, APITimeoutError, APIConnectionError
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage, ModelClientStreamingChunkEvent, ToolCallExecutionEvent, ToolCallRequestEvent, UserInputRequestedEvent, ThoughtEvent, ToolCallSummaryMessage, MultiModalMessage
from autogen_agentchat.teams._group_chat._events import GroupChatMessage
import streamlit as st

from bioGen.biogen import *
from utils import Reward

def create_user_input_func(input_file, log_file):
    def user_input_func(prompt: str) -> str:
        with open(log_file, 'a') as f:
            json.dump({'type': 'prompt', 'prompt_type': 'input', 'content': prompt}, f)
            f.write('\n')
        while True:
            try:
                with open(input_file, 'r') as f: response = f.read().strip()
                if response:
                    with open(input_file, 'w') as f: pass
                    return response
            except: pass
            time.sleep(0.5)
    return user_input_func

def create_user_action_func(input_file, log_file):
    def user_action_func(prompt: str) -> str:
        with open(log_file, 'a') as f:
            json.dump({'type': 'prompt', 'prompt_type': 'action', 'content': prompt}, f)
            f.write('\n')
        while True:
            with open(input_file, 'r') as f: response = f.read().strip()
            if response:
                with open(input_file, 'w') as f: pass
                return response
            time.sleep(0.5)
    return user_action_func

def create_team(storage, persist_dir, file=None, team_summary=False, add_user_prompt=None, logger=None):
    team_state = None
    if file and os.path.exists(file):
        try:
            with open(file, "r") as f: team_state = json.load(f)
        except Exception as e:
            if logger: logger.error(f'Load exist team status {file} error: {e}')
    input_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_input.txt")
    log_file = os.path.join(persist_dir, f"{st.session_state.username}_{st.session_state.project_id}_log.ndjson")
    user_input = create_user_input_func(input_file, log_file)
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
    if team_state and not team_summary:
        try:
            asyncio.run(selector_team2.load_state(team_state))
            st.session_state.init_processing = True
        except Exception as e:
            if logger: logger.error(f'Load exist team status error: {e}')
    else:
        if os.path.exists(input_file): os.remove(input_file)
    return selector_team2

def process_task(user_message, log_file, team, stop_team, force_stop, team_status_file, team_exit_file, team_summary_file, max_content, load_history, sucessfulExecutate_reward, storage, logger=None, parent_pid=None):
    if parent_pid is not None:
        def _monitor_parent():
            while True:
                try:
                    if sys.platform != 'win32' and os.getppid() != parent_pid:
                        os._exit(0)
                    os.kill(parent_pid, 0)
                except OSError:
                    os._exit(0)
                time.sleep(2)
        threading.Thread(target=_monitor_parent, daemon=True).start()

    def _create_file(file):
        if file:
            with open(file, 'w') as f: pass

    def _exit_team(wait_time=10):
        st.session_state.cancellation_token.cancel()
        time.sleep(wait_time)
        return

    def _stop_team_set(team_exit_file):
        if os.path.exists(team_exit_file+'_set'):
            stop_team.set()
            os.remove(team_exit_file+'_set')

    if 'project_id' not in st.session_state:
        project_id = asyncio.run(execute_shell_command_via_api(command=''))
        st.session_state['project_id'] = project_id
        if remote_tool_loaded:
            try: _ = set_remote_tools(tools_dict=remote_tool_detail, project_id=os.environ['PROJECT_ID'], api_base_url=os.environ['API_URL'], api_key=os.environ['API_KEY'], sucessfulExecutate_reward=10)
            except Exception as e: pass

    st.session_state.cancellation_token = CancellationToken()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    max_retries = 5
    retries = 0
    history = []
    if load_history:
        for msg in st.session_state.get('messages', []):
            if 'processed' in msg and not msg['processed']: continue
            source = msg.get('source', msg['role'])
            try: history.append(TextMessage(content=msg['content'], source=source))
            except Exception: pass

    task_messages = history + [TextMessage(content=user_message, source="user")]
    task_messages_num = 0
    reward = Reward(sucessfulExecutate_reward)

    while retries <= max_retries:
        try:
            async_gen = team.run_stream(task=task_messages, cancellation_token=st.session_state.cancellation_token)
            current_source = None
            current_content = ""
            time_out = 60
            try:
                while True:
                    _stop_team_set(team_exit_file)
                    if stop_team.is_set():
                        st.session_state.cancellation_token.cancel()
                        if team_status_file: storage.save_agents(team, team_status_file)
                    if force_stop.is_set():
                        st.session_state.cancellation_token.cancel()
                        time.sleep(10)
                        _create_file(team_exit_file)
                        return
                    msg = loop.run_until_complete(anext(async_gen))
                    if msg is None: break
                    try:
                        if msg.source == "user": continue
                        if "user_proxy:" in msg.content: continue
                        if msg.source == "safety_checker_agent":
                            with open(log_file, 'a') as f:
                                storage.json_safedump({'type': 'toast', 'message': f"Start executing command\nView progression at {os.environ.get('API_URL', 'bioWorker panel')} with your API key", 'icon': "ℹ️", "time": 10}, f)
                                f.write('\n')
                    except Exception: pass

                    if isinstance(msg, TaskResult):
                        termination_msg = "Task terminated. " + (msg.stop_reason or "")
                        with open(log_file, 'a') as f:
                            storage.json_safedump({'type': 'message', 'role': "system", "content": termination_msg}, f)
                            f.write('\n')
                        _create_file(team_exit_file)
                        storage.save_agents(team, team_status_file)
                        break
                    elif isinstance(msg, ThoughtEvent):
                        if current_content:
                            with open(log_file, 'a') as f:
                                storage.json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                        with open(log_file, 'a') as f:
                            storage.json_safedump({'type': 'message', 'role': "thought", "content": msg.content, "source": msg.source}, f)
                            f.write('\n')
                        current_source = None
                        current_content = ""
                    elif isinstance(msg, (ModelClientStreamingChunkEvent, TextMessage, GroupChatMessage, MultiModalMessage)):
                        if msg.source != current_source:
                            if current_content:
                                with open(log_file, 'a') as f:
                                    storage.json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                    f.write('\n')
                            current_source = msg.source
                            current_content = ""
                        if isinstance(msg, ModelClientStreamingChunkEvent):
                            current_content += msg.content
                            with open(log_file, 'a') as f:
                                storage.json_safedump({'type': 'stream_update', 'source': current_source, 'content': current_content}, f)
                                f.write('\n')
                        elif isinstance(msg, (TextMessage, GroupChatMessage)):
                            current_content += msg.content + "\n"
                            with open(log_file, 'a') as f:
                                storage.json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                            if task_messages_num > max_content or 'SUMMARYSUMMARY' in current_content:
                                logger.info(f"Task messages exceeded max_content ({max_content}) or SUMMARYSUMMARY detected. Triggering summary and exit.")
                                ### logger summary path
                                logger.info(f"Creating team summary file: {team_summary_file}")
                                _create_file(team_summary_file)
                                _create_file(team_summary_file + '_no_user_confirm')
                                _exit_team()
                                _create_file(team_exit_file)
                                storage.save_agents(team, team_status_file)
                                ### logger all files state
                                logger.info(f"=======Team status file status=======")
                                logger.info(f"Team status file: {team_status_file}, exists: {os.path.exists(team_status_file)}")
                                logger.info(f"Team exit file: {team_exit_file}, exists: {os.path.exists(team_exit_file)}")
                                logger.info(f"Team summary file: {team_summary_file}, exists: {os.path.exists(team_summary_file)}")
                                logger.info(f"=======End of team status file status=======")
                                reward.reset()
                                with open(log_file, 'a') as f:
                                    storage.json_safedump({'type': 'toast', 'message': f"Start executing command\nView progression at {os.environ.get('API_URL', 'bioWorker panel')} with your API key", 'icon': "ℹ️", "time": 10}, f)
                                    f.write('\n')
                    elif isinstance(msg, ToolCallRequestEvent):
                        with open(log_file, 'a') as f:
                            storage.json_safedump({'type': 'toast', 'message': f"Start executing command\nView progression at {os.environ.get('API_URL', 'bioWorker panel')} with your API key", 'icon': "ℹ️", "time": 999}, f)
                            f.write('\n')
                        time_out = float('inf')
                    elif isinstance(msg, (ToolCallExecutionEvent, ToolCallSummaryMessage)):
                        try: output = msg.content[0].content
                        except: output = str(msg.content)
                        output = f"Execution result:\n```\n{output}\n```"
                        with open(log_file, 'a') as f:
                            storage.json_safedump({'type': 'message', 'role': "system", "content": output}, f)
                            f.write('\n')
                        if not "Error" in output:
                            reward_value = reward('Tool_event')
                            task_messages_num = max(task_messages_num - reward_value, 0)
                        time_out = float('inf')
                    elif isinstance(msg, UserInputRequestedEvent):
                        if current_content:
                            with open(log_file, 'a') as f:
                                storage.json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                                f.write('\n')
                            current_content = ""
                        time_out = float('inf')
                    task_messages_num += 1

            except (asyncio.CancelledError, GeneratorExit):
                with open(log_file, 'a') as f:
                    storage.json_safedump({'type': 'message', 'role': "system", "content": "Task stopped by user. You can resume by providing new input."}, f)
                    f.write('\n')
                if 'stop_team' in st.session_state: st.session_state.stop_team.clear()
                _exit_team()
                _create_file(team_exit_file)
                storage.save_agents(team, team_status_file)
                return

            if current_content:
                with open(log_file, 'a') as f:
                    storage.json_safedump({'type': 'message', 'role': current_source, "content": current_content}, f)
                    f.write('\n')
            _exit_team()
            _create_file(team_exit_file)
            storage.save_agents(team, team_status_file)
            return

        except StopAsyncIteration: pass
        except (RateLimitError, APITimeoutError, APIConnectionError, openai.APIStatusError) as e:
            retries += 1
            with open(log_file, 'a') as f:
                storage.json_safedump({'type': 'message', 'role': "system", "content": f"OpenAI error: {str(e)}. Retry attempt {retries}/{max_retries}."}, f)
                f.write('\n')
            if retries > max_retries:
                _exit_team()
                _create_file(team_exit_file)
                storage.save_agents(team, team_status_file)
                return
            time.sleep(30 * (2 ** (retries - 1)) + random.uniform(0, 10))
        except (BadRequestError, openai.BadRequestError) as e:
            storage.json_safedump({'type': 'message', 'role': "system", "content": f'Out of content number error: {e}, Will summary content and rerun'}, f)
            if team_summary_file:
                _exit_team()
                _create_file(team_exit_file)
                _create_file(team_summary_file)
                storage.save_agents(team, team_status_file)
        except Exception as e:
            with open(log_file, 'a') as f:
                storage.json_safedump({'type': 'message', 'role': "system", "content": f"Unexpected error: {str(e)}"}, f)
                f.write('\n')
            if 'Queue' in str(e) or 'loop' in str(e) or 'The team is already running' in str(e):
                retries = max_retries + 1
            if retries > max_retries:
                storage.save_agents(team, team_status_file)
                _exit_team()
                _create_file(team_exit_file)
                return
            time.sleep(30 * (2 ** (retries - 1)) + random.uniform(0, 10))