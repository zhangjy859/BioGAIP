import os
import sys
import json
import asyncio
import logging
import re
from contextlib import contextmanager

from autogen_agentchat.conditions import TextMentionTermination, ExternalTermination
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
    
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

# Configure standard logger
logger = logging.getLogger(__name__)

@contextmanager
def disable_all_logging():
    logging.disable(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


def load_session(session_file, max_summary_content=10000):
    if not os.path.exists(session_file):
        raise FileNotFoundError(f"Session file not found: {session_file}")
        
    with open(session_file, 'r') as f:
        data = json.load(f)
        message_history = data.get('messages', [])
    
    # 1. Identify indices for system and non-system messages
    #system_indices = [i for i, msg in enumerate(message_history) if msg.get('role') == 'system']
    non_system_indices = [i for i, msg in enumerate(message_history) if msg.get('role') != 'system']
    
    kept_indices = []
    #kept_indices.extend(system_indices) # Always keep all system messages
    
    # 2. Apply truncation rules to non-system messages
    if len(non_system_indices) > max_summary_content + 1:
        first_non_system = non_system_indices[0]
        tail_non_system = non_system_indices[-max_summary_content:]
        
        kept_indices.append(first_non_system)
        kept_indices.extend(tail_non_system)
    else:
        kept_indices.extend(non_system_indices)
        
    # 3. Sort indices to maintain conversation order
    kept_indices = sorted(list(set(kept_indices)))
    
    markdown_str = ""
    last_idx = -1
    
    # 4. Build markdown string and insert truncation notices dynamically
    for idx in kept_indices:
        if last_idx != -1 and idx - last_idx > 1:
            gap_size = idx - last_idx - 1
            markdown_str += f"### Truncated\n\n{gap_size} messages truncated for brevity.\n\n---\n\n"
            
        message = message_history[idx]
        role = message.get('role', 'Unknown')
        content = message.get('content', '')
        markdown_str += f"### {role}\n\n{content}\n\n---\n\n"
        
        last_idx = idx
        
    return markdown_str
    

def get_agent(model, system_prompt):
    ## assume autogen > 0.7.5, model id autogen model class, creat a simple agents to summary markdown
    agent = AssistantAgent(
                name = 'chat_message_summary_agent',
                model_client = model,
                description = 'summary long chat message history',
                system_message = system_prompt,
    )
    return agent


def get_summary_system_prompt(): 
    system_prompt = """
        You are a professional bioinformatics task summarizer. Your ONLY job is to read a long conversation history (provided in Markdown format) and output ONE single, self-contained prompt in English that allows another agent (@planner_agent) to seamlessly continue the ongoing ATAC-seq analysis task.

        You must follow these rules strictly — any deviation will break the pipeline:

        1. NEVER add explanations, apologies, questions, or extra text outside the summary prompt.
        2. NEVER repeat or quote the entire history.
        3. NEVER say "I cannot see the full history" or similar.
        4. Output ONLY the summary prompt, nothing else.

        The output summary prompt MUST start exactly with this line and use this exact structure:

        You are continuing the data analysis task for [A title for task].

        User's original requirements (must be quoted verbatim from the very first user message):
        \"\"\"{{EXACT ORIGINAL USER REQUEST HERE}}\"\"\"

        Tool preferences confirmed by the user (if any):
        {{TOOL PREFERENCES, e.g., "Trim Galore for trimming, Bowtie2 for alignment"}}
        
        Input data structure and format (if have):
        \"\"\"{{EXACT INPUT DATA STRUCTURE AND FORMAT HERE}}\"\"\"

        Completed tasks (bullet list, be precise):
        - Task 1: ..., Output directory is ... (if have)
        - Task 2: ..., Output directory is ... (if have)
        (or write "- None" if nothing is completed yet)

        The last completed task (only read from history, not add your comment): 
        - Task detail, status: (Sucessful or fail), Output directory is ... (if have)

        Remaining/uncompleted tasks (only read from history, not add your comment):
        - Task 3: ...
        - Task 4: ...
        - Task 5: ...
        (or write "- None" if history is not contain unprocess task)
        

        Important paths and constraints:
        NOT ADD YOUR COMMENT
        e.g:
        - Raw data: ... 
        - Reference genome: ...
        - Output directory (must use this): ...
        - Conda env directory: ...
        - Available CPU cores: ...

        @planner_agent Please continue from the current progress. Plan and execute the next step immediately.
        After completing the next step, please check the last completed task output directory.

        Replace the {{PLACEHOLDERS}} above with real content extracted from the history. 
        If a section has no information yet, write "- None" for that section (except the original requirements, which must always be present).
        """
    
    return system_prompt


def _clean_text_rules(text: str) -> str:
    max_code_line_len = 200
    
    # 1. Truncate long lines specifically inside Markdown code blocks
    def truncate_code(match):
        lines = match.group(1).split('\n')
        truncated = [
            line[:max_code_line_len] + " ...[truncated]" if len(line) > max_code_line_len else line
            for line in lines
        ]
        return "```" + "\n".join(truncated) + "```"
        
    text = re.sub(r'```(.*?)```', truncate_code, text, flags=re.DOTALL)
    
    # 2. Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # 3. Compress multiple horizontal whitespaces (avoiding \s+ which destroys newlines)
    text = re.sub(r'[ \t]+', ' ', text)
    # Compress 3 or more blank lines into just two
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def _is_token_limit_error(e: Exception) -> bool:
    logger.warning(f"Exception occurred: {e}")
    err_str = str(e).lower()
    return 'token count exceeds' in err_str or 'maximum number of tokens' in err_str or 'maximum' in err_str or 'context length' in err_str


def run_summary(session_file, model, max_summary_content=10000, user_task=None):
    logger.info(f"Running summary for session file: {session_file} with max_summary_content={max_summary_content}")
    with disable_all_logging():
        system_prompt = get_summary_system_prompt()
        agent = get_agent(model, system_prompt)
        
        def build_user_message(max_content, apply_cleaning=False):
            markdown = load_session(session_file, max_summary_content=max_content)
            user_message = markdown
            if user_task:
                user_message = user_message + '\n===========User firstly task===============\n' + user_task 
            if apply_cleaning:
                user_message = _clean_text_rules(user_message)
            return user_message

        try:
            msg = build_user_message(max_summary_content, apply_cleaning=False)
            summary_prompt = asyncio.run(agent.run(task=msg))
            return summary_prompt.messages[-1].content
        except Exception as e:
            if not _is_token_limit_error(e):
                raise
            
        logging.disable(logging.NOTSET)
        logger.warning(f"Token limit exceeded in Attempt 0. Starting Attempt 1: Applying rule-based text cleaning...")
        logging.disable(logging.CRITICAL + 1)

        try:
            msg = build_user_message(max_summary_content, apply_cleaning=True)
            summary_prompt = asyncio.run(agent.run(task=msg))
            return summary_prompt.messages[-1].content
        except Exception as e:
            if not _is_token_limit_error(e):
                raise

        logging.disable(logging.NOTSET)
        logger.warning(f"Token limit exceeded in Attempt 1. Starting Attempt 2: Decreasing max_summary_content to 50...")
        logging.disable(logging.CRITICAL + 1)
        
        ## out a file to bioGen/debug/summary_debug.log to check the error
        writing_debug_file = True
        if writing_debug_file:
            debug_log_file = os.path.join(os.path.dirname(__file__), 'debug', 'summary_debug.log')
            os.makedirs(os.path.dirname(debug_log_file), exist_ok=True)
            with open(debug_log_file, 'w') as f:
                f.write(f"Token limit exceeded in Attempt 1. Starting Attempt 2: Decreasing max_summary_content to 50...\n")
                f.write(f"System Prompt:\n{system_prompt}\n\n")
                f.write(f"User Message (cleaned):\n{build_user_message(50, apply_cleaning=False)}\n\n")
                #f.write(f"Exception:\n{str(e)}\n")

        msg = build_user_message(50, apply_cleaning=True)
        summary_prompt = asyncio.run(agent.run(task=msg))
        return summary_prompt.messages[-1].content


if __name__ == '__main__':
    # Add simple stream handler to ensure logs are visible in console during execution
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
    
    from bioGen.biogen import *
    session_file = '/mnt/c/Users/zhang/bioGen/cache/user_sessions_fh0pch9a/admin.json'
    content_summary = run_summary(session_file, content_summary_model)
    print("===============output=============")
    print(content_summary)
    print('=====================end=============')
    print('ok')