import sys
sys.path.append('/mnt/e/software/bioGen/')

from bioGen.manager import TeamManager
from bioGen.datamodel import TeamResult, TaskResult
import bioGen.biogen as bg

import autogen
import panel as pn
import openai
import os
import time

manager = bg.selector_team
pn.extension(design="material")

agent_list = [bg.planning_agent, bg.user_proxy, bg.user_chat, bg.query_agent, bg.command_generator_agent, bg.safety_checker_agent, bg.executor_agent, bg.file_agent]

def print_messages(recipient, messages, sender, config):
    chat_interface.send(messages[-1]['content'], user=messages[-1]['name'], avatar=avatar[messages[-1]['name']],
                        respond=False)

    print(
        f"Messages from: {sender.name} sent to: {recipient.name} | num messages: {len(messages)} | message: {messages[-1]}")
    return False, None  # required to ensure the agent communication flow continues

for x in agent_list:
    x.register_reply(
    [autogen.Agent, None],
    reply_func=print_messages,
    config={"callback": None},
)

manager = SelectorGroupChat(
    agent_list,
    model_client=bg.custom_model_client,
    termination_condition=bg.termination,
    selector_prompt=bg.selector_prompt,
    allow_repeated_speaker=True,  # Allow an agent to speak multiple turns in a row.
)

async def callback(contents: str, user: str, instance: pn.chat.ChatInterface):
    manager.run_stream(task=contents)

chat_interface = pn.chat.ChatInterface(callback=callback)
chat_interface.send("Send a message!", user="System", respond=True)
chat_interface.servable()