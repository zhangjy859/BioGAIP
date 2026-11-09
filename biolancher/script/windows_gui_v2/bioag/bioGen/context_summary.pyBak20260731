import os
import sys
import json

from autogen_agentchat.conditions import TextMentionTermination, ExternalTermination
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
    
import asyncio

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

import logging
from contextlib import contextmanager

@contextmanager
def disable_all_logging():
    logging.disable(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


import os
import json

def load_session(session_file, max_summary_content=10000):
    message_history = []
    if os.path.exists(session_file):
        with open(session_file, 'r') as f:
            data = json.load(f)
            message_history = data.get('messages', [])
        
        total_messages = len(message_history)
        if total_messages > max_summary_content + 1:  # +1 to account for keeping the first one
            truncated_count = total_messages - 1 - max_summary_content
            # Keep first message and last max_summary_content messages
            message_history = [message_history[0]] + message_history[-max_summary_content:]
        else:
            truncated_count = 0
        
        markdown_str = ""
        for i, message in enumerate(message_history):
            role = message.get('role', 'Unknown')
            content = message.get('content', '')
            markdown_str += f"### {role}\n\n{content}\n\n---\n\n"
            
            # Insert truncation notice after the first message if truncation occurred
            if i == 0 and truncated_count > 0:
                markdown_str += f"### Truncated\n\n{truncated_count} messages truncated for brevity.\n\n---\n\n"
        
        return markdown_str
    else: 
        raise FileNotFoundError(f"Session file not found: {session_file}")
    
def get_agent(model, system_prompt):
    ## assume autogen > 0.7.5, model id autogen model class, creat a simple agents to summary markdown
    #from autogen import AssistantAgent
    #llm_config = {"config_list": [{"model": model}]}
    #agent_kwargs = {
    #        'name': 'chat message summary agent',
    #        'model_client': model,
    #        'description': 'summary long chat message history',
    #        'system_message': system_prompt,
    #    }
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
    
def run_summary(session_file, model, max_summary_content=10000, user_task = None):
    with disable_all_logging():
        markdown = load_session(session_file, max_summary_content=max_summary_content)
        system_prompt = get_summary_system_prompt()
        #print(system_prompt)
        agent = get_agent(model, system_prompt)
        user_message =  markdown
        if user_task:
            user_message = user_message + '\n===========User firstly task===============\n' + user_task 
        summary_prompt = asyncio.run(agent.run(task=user_message))
        summary_prompt = summary_prompt.messages[-1].content
    return summary_prompt

if __name__ == '__main__':
    from bioGen.biogen import *
    session_file = '/mnt/c/Users/zhang/bioGen/cache/user_sessions_fh0pch9a/admin.json'
    content_summary = run_summary(session_file, content_summary_model)
    print("===============output=============")
    print(content_summary)
    print('=====================end=============')
    print('ok')
    
    



    
