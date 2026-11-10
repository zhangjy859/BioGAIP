import yaml
import os
from textwrap import dedent
import ast
from importlib import import_module
from typing import Dict
import json
import requests
from autogen_agentchat.agents import AssistantAgent
from autogen_core.model_context import BufferedChatCompletionContext

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from azure.core.credentials import AzureKeyCredential
from autogen_core.models import UserMessage
from autogen_ext.models.anthropic import AnthropicChatCompletionClient
from autogen_ext.models.ollama import OllamaChatCompletionClient
from autogen_ext.models.openai import OpenAIChatCompletionClient

from autogen_core.models import SystemMessage

from autogen_core.models import ModelFamily

from autogen_core.tools import FunctionTool

CLIENT_CLASSES = {
    'OpenAIChatCompletionClient': OpenAIChatCompletionClient,
    'AnthropicChatCompletionClient': AnthropicChatCompletionClient,
    'OllamaChatCompletionClient': OllamaChatCompletionClient,
    'AzureOpenAIChatCompletionClient': AzureOpenAIChatCompletionClient,
}

LOAD_CONFIG_DEBUG = False

skip_model_context=os.environ.get("SKIP_MODEL_CONTEXT", "False").lower() == "true"
skip_rag_system_message=os.environ.get("BIOGEN_BYPASSMODE", "False").lower() == "true"
skip_custom_tool_message=os.environ.get("SKIP_CUSTOM_TOOL", "False").lower() == "true"

def load_model_clients(yaml_file: str) -> Dict[str, 'ChatCompletionClient']:
    """
    Parse the YAML file for model_client configurations and load multiple model clients.

    Assumes the YAML structure:
    model_clients:
      client_name1:
        class: 'OpenAIChatCompletionClient'
        kwargs:
          model: 'model_name'
          base_url: 'base_url'
          api_key: '${XAI_API_KEY}'
          max_tokens: 131072
          model_info:
            vision: False
            function_calling: True
            json_output: False
            family: 'gpt-4o'
            structured_output: True
            multiple_system_messages: True
      client_name2:
        class: 'AnthropicChatCompletionClient'
        kwargs:
          model: 'claude-3-opus-20240229'
          api_key: '${ANTHROPIC_API_KEY}'

    Environment variables are resolved if values start with '${VAR_NAME}'.

    :param yaml_file: Path to the YAML configuration file.
    :return: Dictionary of {name: model_client_instance}.
    """
    with open(yaml_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    model_clients = {}
    for name, mc_config in config.get('model_clients', {}).items():
        client_class_name = mc_config['class']
        if client_class_name not in CLIENT_CLASSES:
            raise ValueError(f"Unsupported model client class: {client_class_name}")

        client_class = CLIENT_CLASSES[client_class_name]
        kwargs = mc_config.get('kwargs', {})
        if "family" in kwargs.get("model_info", {}) and kwargs.get("model_info", {}).get("family") == "unknown":
            kwargs["model_info"]["family"] = ModelFamily.UNKNOWN
        # Resolve environment variables in kwargs
        resolved_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, str) and v.startswith('${') and v.endswith('}'):
                var_name = v[2:-1]
                resolved_value = os.getenv(var_name)
                if resolved_value is None:
                    raise ValueError(f"Environment variable {var_name} not set")
                resolved_kwargs[k] = resolved_value
            else:
                resolved_kwargs[k] = v

        model_clients[name] = client_class(**resolved_kwargs)

    return model_clients


def load_tools(yaml_file: str, global_ = False) -> Dict:
    """
    Parse the YAML file for tool configurations and load multiple tools.

    Assumes the YAML structure:
    tools:
      tool_name1:
        name: 'tool1'
        description: 'Description of tool 1.'
        kwargs:
          param1: 'description1'
          param2: 'description2'
        function: 
            def test_tools(value: str):
                return(f"hello {value}")
      tool_name2:
        class: 'AnotherToolClass'
        kwargs:
          paramA: 'valueA'
          ...
      ## IF YAML_FILE is a file load it
      ## IF YAML_FILE is a dicert with main key `tools`, process it
      ## parse each tool config create function and convert it to auto gen FunctionTool
      class FunctionTool(func: Callable[[...], Any], description: str, name: str | None = None, global_imports: Sequence[str | ImportFromModule | Alias] = [], strict: bool = False)[source]
      if global is True, set tool as global tool with tool name as variable name
      if global is False, return all tools as dict, named by tool_name
    """
    from textwrap import dedent
    import ast
    from importlib import import_module
    
    from autogen_core.tools import FunctionTool
    
    if skip_custom_tool_message:
        return {}
    # Load config
    if isinstance(yaml_file, dict):
        config = yaml_file
        if 'tools' not in config:
            return {}
    elif os.path.isfile(yaml_file):
        with open(yaml_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    else:
        config = yaml.safe_load(yaml_file)

    if not config or "tools" not in config:
        return {}

    loaded_tools: Dict[str, Tool] = {}

    for tool_key, cfg in config["tools"].items():
        tool_instance: Any = None
        if "function" in cfg:
            name = cfg.get("name", tool_key)
            description = cfg.get("description", "")

            # Append parameter descriptions to the main description (common pattern)
            if cfg.get("kwargs"):
                description += "\n\nParameters:"
                for param_name, param_desc in cfg["kwargs"].items():
                    description += f"\n  {param_name}: {param_desc}"

            #sys.stderr.write(f(cfg["function"]))
            code = dedent(cfg["function"])

            # Safely extract the first function definition name
            tree = ast.parse(code)
            func_defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            if not func_defs:
                raise ValueError(f"Tool '{tool_key}': no function definition found in 'function' block")
            func_name = func_defs[0].name

            local_ns: Dict[str, Any] = {}
            exec(code, globals(), local_ns)

            func = local_ns.get(func_name)
            if func is None:
                raise ValueError(f"Tool '{tool_key}': function '{func_name}' not found after exec")

            tool_instance = FunctionTool(
                func=func,
                name=name,
                description=description,
                global_imports=[],   # extend if your FunctionTool supports it
                strict=False,
            )

        elif "class" in cfg:
            class_path: str = cfg["class"]
            init_kwargs = cfg.get("kwargs", {})

            module_name, class_name = class_path.rsplit(".", 1)
            module = import_module(module_name)
            cls = getattr(module, class_name)

            tool_instance = cls(**init_kwargs)

            # Allow overriding name/description from YAML
            if "name" in cfg and hasattr(tool_instance, "name"):
                tool_instance.name = cfg["name"]
            if "description" in cfg and hasattr(tool_instance, "description"):
                tool_instance.description = cfg["description"]

        # Skip if neither format was recognised
        if tool_instance is None:
            continue

        if global_:
            globals()[tool_key] = tool_instance
        else:
            loaded_tools[tool_key] = tool_instance

    return {} if global_ else loaded_tools

def generate_remote_tool_description(input_data):
    """
    Generate a Markdown description of remote tools from a YAML file or dictionary.

    Args:
        input_data (str or dict): Path to YAML file or a dictionary containing 'remote_tools'.

    Returns:
        str: Markdown text describing the tools.
    """
    if isinstance(input_data, str):
        if not os.path.exists(input_data):
            return ""
        with open(input_data, 'r') as file:
            data = yaml.safe_load(file)
    elif isinstance(input_data, dict):
        data = input_data
    else:
        raise ValueError("Input must be a YAML file path (str) or a dictionary (dict).")

    remote_tools = data.get('remote_tools', {})
    if not remote_tools:
        return ""

    markdown = "# Available Tools\n\nThese tools are directly available in the analysis environment (via environment variables).\n\n## Tool List\n\n"

    # List all tools
    for tool_key in remote_tools:
        markdown += f"- **{tool_key}**: {remote_tools[tool_key].get('description', 'No description provided.')}\n"
    
    markdown += "\n## Tool Usage Details\n\n"

    # Detailed usage for each tool
    for tool_key, tool_info in remote_tools.items():
        name = tool_info.get('name', tool_key)
        description = tool_info.get('description', 'No description provided.')
        usage = tool_info.get('usage', 'No usage provided.').strip()
        kwargs = tool_info.get('kwargs', 'No arguments provided.').strip()

        markdown += f"### {name} ({tool_key})\n\n**Description:** {description}\n\n**Usage:**\n```\n{usage}\n```\n\n**Arguments:**\n```\n{kwargs}\n```\n\n"

    return markdown

def extract_remote_tools_detail(input_data):
    """
    Extract remote tools from a YAML file or dictionary and return them as a dictionary
    with tool keys containing name, description, and script.

    Args:
        input_data (str or dict): Path to YAML file or a dictionary containing 'remote_tools'.

    Returns:
        dict: A dictionary where each key is a tool name, and the value is another dict
              with 'name', 'description', and 'script'.
    """
    if isinstance(input_data, str):
        if not os.path.exists(input_data):
            raise ValueError(f"YAML file '{input_data}' not found.")
        with open(input_data, 'r') as file:
            data = yaml.safe_load(file)
    elif isinstance(input_data, dict):
        data = input_data
    else:
        raise ValueError("Input must be a YAML file path (str) or a dictionary (dict).")

    remote_tools = data.get('remote_tools', {})
    if not remote_tools:
        return {}

    result = {}
    for tool_key, tool_info in remote_tools.items():
        name = tool_info.get('name', tool_key)
        description = tool_info.get('description', 'No description provided.')
        script = tool_info.get('script', '').strip()
        
        result[tool_key] = {
            'name': name,
            'description': description,
            'script': script
        }

    return result

def set_remote_tools(tools_dict: dict, project_id: str, api_base_url: str, api_key: str, working_dir: str = None) -> dict:
    """
    Set tools via the API by dumping the tools dict to a JSON file and calling the import-tools endpoint.

    Args:
        tools_dict (dict): The dictionary returned by extract_tools_as_dict.
        project_id (str): The ID of the project.
        api_base_url (str): The base URL of the API (e.g., 'http://localhost:38000').
        api_key (str): The API key for authentication.
        working_dir (str, optional): The working directory to save the JSON file. Defaults to current directory.

    Returns:
        dict: The JSON response from the API.
    """
    if working_dir is None:
        working_dir = os.getcwd()
    
    json_filename = f"{project_id}_tools.json"
    json_path = os.path.join(working_dir, json_filename)
    
    with open(json_path, 'w') as f:
        json.dump(tools_dict, f, indent=4)
    
    url = f"{api_base_url}/projects/{project_id}/import-tools"
    headers = {"x-api-key": api_key}
    data = {"json_file": json_filename}  # Use relative path if working_dir is the project's working dir
    
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()  # Raise error if not successful
    
    return response.json()

def load_agents(yaml_file: str, model_clients: Dict[str, 'ChatCompletionClient'], default_model_client: str, memory = None, tools = None, skip_params_model_content = None, remote_tools=None) -> Dict[str, AssistantAgent]:
    """
    Parse the YAML file for agent configurations and load the agents using provided model_clients.

    Assumes the YAML structure:
    agents:
      agent_name1:
        model_client: 'client_name1'  # Key from model_clients dict
        description: 'Description of the agent.'
        system_message: 'System message for the agent.'
        additional_params:

      agent_name2:
        model_client: 'client_name2'
        description: 'Another description.'
        system_message: 'Another system message.'

    :param yaml_file: Path to the YAML configuration file.
    :param model_clients: Dictionary of loaded model clients {name: instance}.
    :return: Dictionary of {agent_name: AssistantAgent instance}.
    """
    with open(yaml_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    skip_model_context = os.environ.get("SKIP_MODEL_CONTEXT", "False").lower() == "true"
    if skip_params_model_content is not None:
        skip_model_context = skip_params_model_content

    agents = {}
    for name, agent_config in config.get('agents', {}).items():
        if LOAD_CONFIG_DEBUG: print(f"Loading agent '{name}' with config: {agent_config}")
        model_client_name = agent_config.get('model_client', default_model_client)
        if model_client_name not in model_clients:
            raise ValueError(f"Model client '{model_client_name}' not found in loaded model_clients")

        model_client = model_clients[model_client_name]
        description = agent_config['description']
        system_message = agent_config['system_message']
        additional_params = agent_config.get('additional_params', {})
        
        if agent_config.get('allow_remote_tools', False) and remote_tools is not None:
            system_message = system_message + '\n' + remote_tools

        agent_kwargs = {
            'name': name,
            'model_client': model_client,
            'description': description,
            'system_message': system_message,
        }

        if 'model_context' in agent_config.keys() and not skip_model_context:
            ## check if model_context is defined as int
            if isinstance(agent_config['model_context'], int):
                agent_kwargs['model_context'] = BufferedChatCompletionContext(agent_config['model_context'], initial_messages=[SystemMessage(content=system_message)])
            else:
                raise ValueError(f"Model context '{agent_config['model_context']}' not found in loaded model_clients")
            #agent_kwargs['model_context'] = BufferedChatCompletionContext(agent_config['model_context'])

        if not LOAD_CONFIG_DEBUG:
            if memory is not None and 'memory' in agent_config.keys() and skip_rag_system_message:
                agent_memory = [memory[mem_name] for mem_name in agent_config['memory'] if mem_name in memory]
                agent_kwargs['memory'] = agent_memory

            if tools is not None and 'tools' in agent_config.keys():
                print('+++++++++++loading tools+++++++++++++')
                #print(tools)
                print(agent_config['tools'])
                #print(tools.keys())
                agent_tools = [tools.get(tool_name, None) for tool_name in agent_config['tools']]
                if None in agent_tools:
                    missing_tools = [agent_config['tools'][i] for i, t in enumerate(agent_tools) if t is None]
                    raise ValueError(f"Tools {missing_tools} not found in provided tools dictionary")
                print(agent_tools)
                print('===================================')
                agent_kwargs['tools'] = agent_tools

        agent_kwargs.update(additional_params)

        agents[name] = AssistantAgent(**agent_kwargs)
        
        #if buffer_size is not None:
        #    if hasattr(agents[name].model_context, 'buffer_size'):
        #        agents[name].model_context.buffer_size = buffer_size

    return agents

if __name__ == "__main__":
    # Example usage
    LOAD_CONFIG_DEBUG = True
    model_clients = load_model_clients('system_config.yaml')
    for name, client in model_clients.items():
        print(f"Loaded model client '{name}': {client}")
    agents = load_agents('system_config.yaml', model_clients, default_model_client='OpenAIChatCompletionClient')
    for name, agent in agents.items():
        print(f"Loaded agent '{name}': {agent}")
