import chainlit as cl
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import TextMessage, ModelClientStreamingChunkEvent, ToolCallExecutionEvent, \
    ToolCallRequestEvent
from autogen_agentchat.teams._group_chat._events import GroupChatMessage
from chainlit import AskUserMessage, Message
import sys
from typing import List, cast

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

sys.path.append('/mnt/e/software/bioGen')
sys.path.append('/mnt/e/software/bioGen/bioGen')

from bioGen.biogen import *
import sys, os


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="RNA-seq",
            message="""
                Objective: Perform RNA-Seq analysis, including transcript abundance quantification and differential expression analysis (DEA), using STAR for alignment and featureCounts for quantification. Store results in /RNA-seq.
                Expected Outputs:

                Aligned BAM files with corresponding indices.
                Transcript abundance counts.
                Differential Expression Analysis (DEA) using DESeq2, performed if grouping information is provided or can be inferred from FASTQ file names.

                User Input Requirements:Please provide the following details to proceed with the analysis:

                FASTQ File Location:

                Specify the directory path containing your RNA-Seq FASTQ files.


                Reference Genome and Annotation:

                Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
                Annotation File (GTF/GFF3 format): Provide the full path to the gene annotation file.
                Optional: If needed, download resources from Ensembl or UCSC Genome Browser. For example, use wget to retrieve files like Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz or Homo_sapiens.GRCh38.108.gtf.gz from Ensembl.


                Grouping Information for DEA:

                Provide Grouping Information: Submit experimental group details (e.g., 'control', 'treatment') in a comma-separated list or table linking each FASTQ file to a group.
                Infer from FASTQ File Names: If group information can be derived from FASTQ file names (e.g., sample1_control_R1.fastq.gz, sample2_treatment_R1.fastq.gz), describe the naming convention.


                Optional Parameters:

                Number of Threads: Specify the number of CPU threads available to optimize processing speed.



                Instructions:

                ASK USER the requested information to initiate the analysis.
                After receiving the inputs, the system will summarize the provided details, perform the analysis, and store results in /RNA-seq.
                Upon completion, confirm with the user if additional tasks are needed. 

            """,
            icon="https://dataweb.biogaip.top/img/ngs.png?expires=1860895542&token=3eb01cbf55ce9ca512e66e52a2d525722cf778f3064242e5127c5624af810793",
        ),

        cl.Starter(
            label="WGS analysis",
            message="""
                Objective: Perform Whole Genome Sequencing (WGS) analysis, including read alignment, variant calling, and variant annotation. Use BWA for alignment, GATK for variant calling, and ANNOVAR or similar for annotation. Store results in /WGS.
                Expected Outputs:
                Aligned BAM files with indices.
                Variant Call Format (VCF) files containing single nucleotide variants (SNVs) and indels.
                Annotated variants with functional predictions.
                User Input Requirements: Please provide the following details to proceed with the analysis:
                FASTQ File Location:
                Specify the directory path containing your WGS FASTQ files.
                Reference Genome:
                Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
                Optional: Download from Ensembl or UCSC, e.g., Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.
                Known Variants (optional for recalibration):
                Provide paths to known variant sites (e.g., dbSNP, Mills indels) if available.
                Optional Parameters:
                Number of Threads: Specify CPU threads for faster processing.
                Instructions:
                ASK USER the requested information to start the analysis.
                The system will summarize inputs, execute the pipeline, and store results in /WGS.
                Upon completion, ask if further analysis is required.
            """,
            icon="https://dataweb.biogaip.top/img/wgs.png?expires=1860895570&token=76c9be71a110804eea63d1af6f247f6161fbefdee16518bab5e27460404f511e",
        ),
        cl.Starter(
            label="ATAC-seq",
            message="""
                Objective: Perform ATAC-Seq analysis to assess chromatin accessibility, including read alignment, peak calling, and differential accessibility analysis. Use Bowtie2 for alignment and MACS2 for peak calling. Store results in /ATAC-seq.
                Expected Outputs:
                Aligned BAM files with indices.
                Peak files in BED or narrowPeak format.
                Differential accessibility results if grouping is provided.
                User Input Requirements: Please provide the following details to proceed with the analysis:
                FASTQ File Location:
                Specify the directory path containing your ATAC-Seq FASTQ files.
                Reference Genome:
                Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
                Optional: Download from Ensembl or UCSC, e.g., Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.
                Grouping Information (for differential analysis):
                Provide group details (e.g., 'control', 'treatment') linked to FASTQ files, or describe naming convention for inference.
                Optional Parameters:
                Number of Threads: Specify CPU threads for optimization.
                Instructions:
                ASK USER the requested information to initiate the analysis.
                The system will summarize inputs, perform the analysis, and store results in /ATAC-seq.
                Upon completion, confirm if additional tasks are needed.
            """,
            icon="https://dataweb.biogaip.top/img/Transposase_ATAC.svg?expires=1860895505&token=e89cbda998025f0bac6ffd9e7cb40a7b91366e6bef147d797fa948779f9a32e7"
        )
    ]


async def user_input_func(prompt: str, cancellation_token: CancellationToken | None = None) -> str:
    """Get user input from the UI for the user proxy agent."""
    try:
        response = await cl.AskUserMessage(content=prompt, timeout=999999).send()
    except TimeoutError:
        return "User did not provide any input within the time limit."
    if response:
        return response["output"]  # type: ignore
    else:
        return "User did not provide any input."


async def user_action_func(prompt: str, cancellation_token: CancellationToken | None = None) -> str:
    """Get user action from the UI for the user proxy agent."""
    try:
        response = await cl.AskActionMessage(
            content="Pick an action",
            actions=[
                cl.Action(name="approve", label="Approve", payload={"value": "approve"}),
                cl.Action(name="reject", label="Reject", payload={"value": "reject"}),
            ],
        ).send()
    except TimeoutError:
        return "User did not provide any input within the time limit."
    if response and response.get("payload"):  # type: ignore
        if response.get("payload").get("value") == "approve":  # type: ignore
            return "APPROVE."  # This is the termination condition.
        else:
            return "REJECT."
    else:
        return "User did not provide any input."


tasks = """
    You are a knowledgeable bioinformatics assistant. You run in a Linux environment. \
    Assume workdir is {work_dir_env}, \
    You need to understand the user's requirements about specific Bioinformatics tasks, \
    first call @user_proxy to get user input, \
    check the legitimacy of the requirements, and implement them through appropriate and secure Linux commands. \
    If necessary, before fulfilling the user's requirements, you can decide to ask @system_check_agent to generate command to check the system or confirm some information (eg: software version). These commands must also undergo security checks. \
    @bio_micromamba_env_agent could help prepare micromamba env, all new envs should store at [work_dir]/envs \
    @file_agent could help you list file in specific path and subdir as json format, \
    When a certain method fails, you need to try different methods and share the information with team members you will asked. \
    If multiple attempts fail, require user's help or terminate the process. You also can search web by @web_surfer_agent,\
    please note that you cannot assume or perform any operations as superusers. \
    You need to be aware that you may have a limited context length. To maintain focus on the task during long conversation, update necessary memory via @manager_mem_agent.  \
    Only one agents called each time
""".format(work_dir_env=os.environ['WORK_DIR'])


## document: https://github.com/microsoft/autogen/blob/main/python/samples/agentchat_chainlit/app_team_user_proxy.py
@cl.on_chat_start
async def on_chat_start():
    print(__name__)
    user_proxy = UserProxyAgent('user_proxy', input_func=user_input_func)

    ## remove user_proxy from agents_non_proxy
    agents_non_proxy = [agent for agent in agents if agent.name != 'user_proxy']

    agents_non_proxy.append(user_proxy)
    ## debug
    for x in agents_non_proxy:
        print(x.name)
    selector_team2 = SelectorGroupChat(
        agents_non_proxy,
        model_client=default_model,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=False,  # Allow an agent to speak multiple turns in a row.
    )
    cl.user_session.set("prompt_history", "")  # type: ignore
    cl.user_session.set("team", selector_team2)
    cl.user_session.set("agents_non_proxy", agents_non_proxy)

    ## web shell project
    project_id = await execute_shell_command_via_api(command='')
    cl.user_session.set("project_id", project_id)

    thread_id = cl.context.session.thread_id

    if thread_id:
        data_layer = get_data_layer()
        await data_layer.update_thread(thread_id, metadata={"project_id": project_id})

    # await selector_team2.run(task=tasks)


@cl.on_message  # type: ignore
async def chat(message: cl.Message) -> None:
    # Get the team from the user session.
    team = cast(RoundRobinGroupChat, cl.user_session.get("team"))  # type: ignore
    # Streaming response message.
    streaming_response: cl.Message | None = None
    # Stream the messages from the team.
    first_task = message.content
    ## task message
    task_list = cl.TaskList()
    task_list.status = "Running..."
    async for msg in team.run_stream(
            task=[TextMessage(content=message.content, source="user")],
            cancellation_token=CancellationToken(),
    ):
        print(f'got message: {msg}')
        if msg is not None and not isinstance(msg, TaskResult) and msg.source == "user":
            # Skip user messages as they are already displayed in the UI.
            pass
        elif isinstance(msg, ModelClientStreamingChunkEvent):
            print(f'<<<got chunk event: {msg}')
            # Stream the model client response to the user.
            if streaming_response is None:
                # Start a new streaming response.
                streaming_response = cl.Message(content="", author=msg.source)
            await streaming_response.stream_token(msg.content)
        elif streaming_response is not None:
            print(f'>>>got streaming response: {streaming_response}')
            # Done streaming the model client response.
            # We can skip the current message as it is just the complete message
            # of the streaming response.
            await streaming_response.send()
            # Reset the streaming response so we won't enter this block again
            # until the next streaming response is complete.
            streaming_response = None
        elif isinstance(msg, TaskResult):
            print(f'<<<got task result: {msg}')
            # Send the task termination message.
            final_message = "Task terminated. "
            if msg.stop_reason:
                final_message += msg.stop_reason
            await cl.Message(content=final_message).send()
        elif isinstance(msg, GroupChatMessage):
            print(f'>>>got group chat message: {msg}')
            # Send the group chat message.
            await cl.Message(content=msg.content, author=msg.source).send()
        elif isinstance(msg, TextMessage) and msg.source != 'user_proxy':
            print(f'<<<got text message: {msg}')
            if msg.source is not None and msg.content.__contains__('user_proxy'):
                pass
            # Send the text message.
            else:
                await cl.Message(content=msg.content, author=msg.source).send()
        elif isinstance(msg, ToolCallExecutionEvent) or isinstance(msg, ToolCallRequestEvent):
            await cl.context.emitter.send_toast(
                message=f"Start executing command\nView progression at {os.environ.get('API_URL')} with your API key",
                type="info")
            await cl.context.emitter.send_toast(
                message=f"This page will auto refresh after command execution is complete.",
                type="info")
            await cl.Message(content=msg.content[0].content).send()
        else:
            # Skip all other message types.
            pass


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    app_user = os.environ.get('APP_USER')
    if app_user:
        try:
            expected_username, expected_password = app_user.split(':', 1)
            if (username == expected_username) and (password == expected_password):
                return cl.User(
                    identifier=username, metadata={"role": "admin", "provider": "credentials"}
                )
        except ValueError:
            pass
    return None


@cl.data_layer
def get_data_layer():
    # https://docs.sqlalchemy.org/en/14/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg
    return SQLAlchemyDataLayer(conninfo="postgresql+asyncpg://postgres:biogendata@127.0.0.1:5432/chainlit_db")

# @cl.on_chat_resume
# async def on_chat_resume(thread):
#    project_id = thread.get("metadata", {}).get("project_id", None)
#    if project_id is None:
#        logger.error('No project_id found in thread metadata')
#    else:
#        os.environ['PROJECT_ID'] = project_id
#    historical_messages = []
#    print('+++++thread+++++')
#    print(thread)
#    print('+++++++++++++++')
#    for msg in thread.get('steps', []):
#        print('+++++msg+++++')
#        print(msg)
#        print('+++++++++++++')
#        historical_messages.append({
#            "content": msg.get("output", ""),
#            "role": msg.get('name')
#        })
#
#    agents_non_proxy = [agent for agent in agents if agent.name != 'user_proxy']
#
#    agents_non_proxy.append(user_proxy)
#
#    selector_team2 = cast(RoundRobinGroupChat, agents_non_proxy)  # type: ignore
#    print('+++++on_chat_resume+++++')
#    print(cl.user_session.get('project_id'))
#    print('+++++++++++++++++++++++')
#    await cl.Message(content="Resumed conversation!").send()
#    pass