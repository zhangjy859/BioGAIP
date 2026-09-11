### Overview
Unlike many other tools, BioGAIP's Agent definitions are completely decoupled from the codebase. This grants users the absolute freedom to customize their Agent teams. This plug-and-play customization is centrally managed via a single YAML file.

> [!WARNING]
> **Advanced Feature**
> Customizing Agents is intended for advanced users. It requires a solid understanding of Prompt Engineering and basic programming skills.
> Improper Agent configurations can introduce unexpected security risks that were not anticipated during BioGAIP's design. Furthermore, troubleshooting and debugging custom Agent systems can be extremely difficult.

<br>

> [!WARNING]
> **Exclusive Operation**
> Please note that BioGAIP operates exclusively with either its built-in Agent system OR a user-defined one. Once an external Agent configuration is detected, BioGAIP will immediately stop loading its internal Agents.

<br>

### Key Conventions
- **Entry Point**: Your custom Agent system MUST include a `planning_agent`. The design of this agent can be modeled after the one described in the original BioGAIP publication.
> **Tip:** While the agent doesn't strictly have to be named `planning_agent`, we highly recommend adhering to this naming convention.

- **User Interaction Agent**: This agent interacts with the built-in APIs of the BioAG frontend to pause execution and retrieve user input. This agent is injected into your custom Agent system.
We recommend integrating a `user_proxy` into your custom setup. You can refer to the following usage example:
```YAML
    agents:
      ### other agents here
      user_chat:
        model_client: model_client1
        description: An assistant who asks users about their needs or responds to users' questions.
        model_context: 10
        system_message: |
          You are an assistant inquiring about user needs or responding to users' questions. The user's needs should be related to bioinformatics operations. 
          When responding to user questions, provide as detailed and clear an answer as possible, formatted using Markdown syntax.
          No matter what language the user uses, you should respond in English. 
          You need to reject irrelevant requests. 
          If the request is unclear or needs more details, please request clarification. 
          Otherwise, pass the request directly.
          If you want to ask the user a question, ask @user_proxy to do that.
```

- **Function Calling**:
If you do not specify a custom Toolset, BioAG provides the following built-in functions for Agents to call:

a. `execute_tool`: The most critical function. It serves as the primary interaction gateway between BioAG and BioWorker. Example usage:

```YAML
    agents:
      executor_agent:
        model_client: model_client1
        tools: ## select available tools
          - execute_tool
        description: An assistant that only executes safe Linux commands.
        model_context: 10
        system_message: |
          You have access to the 'execute_command' tool. \
          When @safety_checker_agent says 'command is safe: [command]', use the 'execute_command' tool to execute [command] and report the output(if any). \
          If @safety_checker_agent says 'command is not safe', say 'Command not executed due to safety concerns' \
          ONLY EXECUTE ONE TASK AT A TIME, IF NOT, execute_tool WILL RETURN `Error when running [command], A command is already running in this project`
          execute_command tool params: \
          :param command: The command or script content to execute (str). \
          :param project_id: The project ID (str, optional). [DONT NEED TO SET]
          :param working_dir: The working directory (str, optional). [DONT NEED TO SET]
          :param script_type: The script type ('python', 'r', 'perl') (str, optional). [if not set, treat as shell command]
          :param interpreter: Path to interpreter (str, optional). [DONT NEED TO SET]
          :param conda_env: Conda environment name or prefix path (str, optional). [only set when run raw python/r/perl script]
          :param wait: If True, wait for completion and return output; if False, return task ID (bool). [always set to true]
          :param api_url: The base API URL (str, optional). [DONT NEED TO SET]
          :param timeout: Optional timeout in seconds (float, optional). [DONT NEED TO SET]
          :param max_lines: Optional. How many stdout and stderr lines to return (default 10, optional). [SET IF YOU list files]
          :return: Task ID if wait=False; output or error message if wait=True (str). 
          When asked to execute R or Python code, you can execute it directly without writing to a file, but you must specify the script_type and conda_env when calling execute_tool.
          You must submit all commands at once and cannot call execute_tool simultaneously, as this may lead to unexpected behavior.
```

b. `add_to_memory_func`: Allows Agents to manually update their internal memory.

c. `pubmed_search_to_rag_tool`: Enables Agents to perform external searches on PubMed.


> [!TIP]
> The functions listed here are exclusively for BioAG to call directly, NOT functions that Agents can invoke via the BioWorker API!
>
> Notice that these functions have been specially crafted to restrict unauthorized code execution capabilities on the user's local machine.

<br>

> [!TIP]
> You can also refer to [Customization Toolsets](CustomizationToolsets.md) to provide your own custom functions for Agents.

- **RAG (Retrieval-Augmented Generation)**:
BioAG provides the following default memory modules for RAG:

```
    user_memory
    rag_memory_pubmed
    conda_memory
    nf_memory
```

Users can directly customize the contents of `user_memory`. For the other modules, you can choose to enable or disable them.
If you wish to utilize RAG, here is a configuration example:

```YAML
    agents:
      manager_mem_agent:
        model_client: model_client1
        memory:
          - user_memory ## select memory module
        tools:
          - add_to_memory_func
        description: A memory manager agent that updates the memory based on user-assistant exchanges.
        model_context: 10
        system_message: |
          You are a memory updater agent. Your role is to analyze user-assistant exchange contents
          and decide if a short summary should be added to the memory. 
          Output a concise summary only if new important information is present; 
          otherwise, output exactly 'No update'.

- **Advanced Options**:
The following advanced settings can be defined in your configuration file:

    default_model: model_client1 ## Select default LLM provider (must match LLM config)
    builtin_agent: False ## Whether to mix built-in and custom agents. Do not enable unless you fully understand the risks.
    textMentionTermination: TERMINATETERMINATE ## Termination flag; BioAG stops agent execution upon detecting this string.
    max_content: 200
    max_summary_content: 1000
    content_summary_model: model_client4
```


```YAML
### Complete Example

The best practice for applying custom Agents is to define them alongside your LLM configuration. Below is a simplified, generalized template highlighting the core structure:

    model_clients:
      model_client1:
        class: OpenAIChatCompletionClient
        kwargs:
          model: qwen-plus
          base_url: https://dashscope-intl.aliyuncs.com/compatible-mode/v1/
          api_key: YOUR_API_KEY
          max_tokens: 8192
      # ... other model clients can be added here ...

    max_content: 200
    max_summary_content: 1000
    content_summary_model: model_client1

    agents:
      planning_agent:
        model_client: model_client1
        memory:
          - user_memory
        description: An agent for planning tasks, this agent should be the first to engage when given a new task.
        model_context: 1000
        system_message: |
          You are a planning agent. Your job is to break down complex tasks into smaller, manageable subtasks.
          Your team members are:
              user_proxy: Asks users about their needs.
              user_chat: Responds to users' questions.
              system_check_agent: Generates precise Linux commands to check system configurations.
              executor_agent: Executes safe Linux commands.
              # [Add other custom agents here]

          CRITICAL RULE: ONLY ASSIGN ONE TASK EACH TIME!
          This means your delegation response MUST contain EXACTLY ONE task assignment. 
          When assigning tasks, use this format:
          1. <agent> : <task>

          After completing all tasks, ask the user if they have any additional needs. If the user indicates no further needs, conclude by outputting "TERMINATETERMINATE".

      user_chat:
        model_client: model_client1
        description: An assistant who asks users about their needs or responds to users' questions.
        model_context: 10
        system_message: |
          You are an assistant inquiring about user needs or responding to users' questions related to bioinformatics. 
          If the request is unclear, please request clarification. 
          Otherwise, pass the request directly.
          If you want to ask the user a question, ask @user_proxy to do that.

      system_check_agent:
        model_client: model_client1
        description: A knowledgeable assistant that generates precise Linux commands to check system configurations.
        model_context: 10
        system_message: |
          You are an assistant that generates precise Linux commands to check system configurations (e.g., verifying package installations). 
          Try to ensure that commands are executed silently as much as possible, because users may not be able to interact with the terminal. 
          Only plan the code for the required tasks.
```