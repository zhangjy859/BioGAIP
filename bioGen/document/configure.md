# Configure
bioGen is designed to minimize redundant configurations as much as possible. bioAG requires a predefined configuration folder, which contains two subfolders:
 - `config/system.yaml`: configuration fil agents system settings, such as `LLM API URL`, `API key` and `agents` role
 - `config/.envs`: some globel environment variables, such as `bioWorker` server address and `bioWorker` server port

>**[info] info**
> 
> The configure template files are located in the `bioGen/config`, a zip file also can be download from [xxx](xxx)
> 

## Step 1: Configure system.yaml
The default system.yaml template contains the agents role definitions required by bioAG. 
To make it work properly, users need to modify the model clients definition at the top of the file, 
which looks like this:

>[!WARNING]
> 
> If you are not using the custom Agents system, you must use our configuration file template. 
> You can only modify the parameters of the file, but not its structure. For example, you must maintain the four Clients configuration; otherwise, the software will not be able to run. 
>

```yaml
model_clients:
  ## IF YOUR ONLY WANT USE ONE CLIENT, SET ALL model_client configure to same
  model_client1:
    class: OpenAIChatCompletionClient
    kwargs:
      model: qwen-plus # REPLACE_WITH_YOUR_API_MODEL_NAME
      base_url: REPLACE_WITH_YOUR_API_URL
      api_key: REPLACE_WITH_YOUR_API_KEY
      max_tokens: 8192
      model_info:
        vision: False
        function_calling: True
        json_output: True
        family: unknown
        structured_output: True
        multiple_system_messages: True
  model_client2:
    class: OpenAIChatCompletionClient
    kwargs:
      model: qwen-plus # REPLACE_WITH_YOUR_API_MODEL_NAME
      base_url: REPLACE_WITH_YOUR_API_URL
      api_key: REPLACE_WITH_YOUR_API_KEY
      max_tokens: 8192
      model_info:
        vision: False
        function_calling: True
        json_output: True
        family: unknown
        structured_output: True
        multiple_system_messages: True
  model_client3:
    class: OpenAIChatCompletionClient
    kwargs:
      model: qwen-plus # REPLACE_WITH_YOUR_API_MODEL_NAME
      base_url: REPLACE_WITH_YOUR_API_URL
      api_key: REPLACE_WITH_YOUR_API_KEY
      max_tokens: 8192
      model_info:
        vision: False
        function_calling: True
        json_output: True
        family: unknown
        structured_output: True
        multiple_system_messages: True
  model_client4:
    class: OpenAIChatCompletionClient
    kwargs:
      model: grok-4-fast-reasoning # REPLACE_WITH_YOUR_API_MODEL_NAME
      base_url: REPLACE_WITH_YOUR_API_URL
      api_key: REPLACE_WITH_YOUR_API_KEY
      max_tokens: 2000000
      model_info:
        vision: False
        function_calling: True
        json_output: False
        family: unknown
        structured_output: True
        multiple_system_messages: True
        thinking: True
  # NOT USE
  anthropic_client:
    class: AnthropicChatCompletionClient
    kwargs:
      model: claude-3-opus-20240229
      api_key: ANTHROPIC_API_KEY

max_content: 100 ## If the conversation duration exceeds this limit, a Summary will be triggered to summarize and refresh the current conversation in order to prevent hallucinations.
content_summary_model: model_client4 ## Use which model to run Summary
max_summary_content: 300 # how many conversation to summary

```

`bioGen` allow users to define multiple model clients, and assign them to different agents. 
By defaults, three model clients are defined in the template file: `model_client1`, `model_client2` and `model_client3`. You can modify the `class` and `kwargs` fields to match your LLM provider's API.
if you only have one LLM model client, you can change all the model clients configure for same.

`bioGen` Support OpenAI API compatible models, such as `OpenAI`, `Grok`, `Anthropic`, `Cohere` and `HuggingFace`. But also support other API Endpoints, 
such as AzureOpenAIChatCompletionClient (Microsoft Azure OpenAI Service), GeminiChatCompletionClient(Google Gemini).

D

Under normal circumstances, there are three items that must be modified: 
 - model: the model name you want to use
 - base_url: the API base URL of your LLM provider
 - api_key: the API key for accessing the LLM provider

This information can usually be found in your LLM provider. for example: 
 - OpenAI: https://openai.com/
 - Grok: https://console.x.ai/
 - Gemini: https://aistudio.google.com/
 - DeepSeek: https://api-docs.deepseek.com/
 - ...

## config.yaml
>**[warning] warning**
> 
> If you use containerization technology (docker or Singularity) to run `bioGen`, you do not need to configure this section.
>

This is user prefernece configuration file, you can modify the agents definition,
    which looks like this:
```yaml
bioAG:
  ## all paths should be absolute paths in local computer
  CONDA_META_DATABASE: ''
  WORKFLOW_DATABASE: ''
  USER_EXT_DATABASE: ''
  API_URL: ''
  API_KEY: ''
  ## deprecated Settings, dont use
  ASK_EXEC: 'False'
  MARKDOWN_RENDERER: 'TRUE'
  ## deprecated Settings end
bioWorker:
    ## all paths should be absolute paths in remote computer
    WORK_DIR: '/data/work_dir'
```


