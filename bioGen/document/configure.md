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


# Environment Variables & Configuration Reference

BioGAIP provides fine-grained control over system paths, BioWorker API connections, authentication, logging, persistent storage, RAG memory databases, and agent behaviors through environment variables and YAML configuration files.

---

## ⚙️ Configuration File Overrides

By default, BioGAIP resolves its configuration directory relative to the package directory or `/config`. You can explicitly override configuration file locations using the variables below:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `SYSTEM_CONFIG_PATH` | String (Directory Path) | `/config` or package `config/` | Directory path containing default configuration YAML files (`system_config.yaml`, `config.yaml`, `agent_config.yaml`, `tool_config.yaml`). |
| `SYSTEM_CONFIG_YAML_PATH` | String (File Path) | *None* | Absolute path to a specific `system_config.yaml` file. If specified, overrides the default path resolution for the system configuration. |

---

## 🔐 Web UI Authentication & Cookie Security

These variables manage user access control and frontend session encryption:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_USER` | String (Inline or File Path) | `"admin:admin"` | Configures authentication credentials. Can be either an inline `username:password` string or a file path to an htpasswd-like file containing `username:password` pairs (one per line, `#` comments ignored). |
| `PASSWORD_SALT` | String | *None* | Optional cryptographic salt string. When provided, passwords are authenticated using SHA-256 hashing (`SHA256(password + salt)`). |
| `COOKIE_PASSWORD` | String (Hex) | *Auto-generated 64-byte hex* | Encryption key used by `EncryptedCookieManager` to secure browser session cookies. Specify a fixed string to persist user login states across service restarts. |

---

## 💾 Storage, Session Persistence & Logging

These variables govern where session states, temporary task files, and system logs are stored:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PERSIST_DIR` | String (Directory Path) | `<work_dir>/user_sessions_<hex>` | Directory path where persistent user sessions, task status files (`.agjson`), communication queues, and process PIDs are stored. |
| `MAX_CHAT_MESSAGE` | Integer | `200` | Maximum number of chat messages retained in memory per session history. |
| `REDIRECT_LOGGER_TO_PERSIST_DIR`| String (`"true"` / `"false"`) | `"false"` | When set to `1`, `true`, or `yes`, automatically directs logger output to `redirected_app.log` located inside `PERSIST_DIR`. |
| `LOG_DIR` | String (Directory Path) | *None* | Custom directory path for writing system logs (`app.log`). |
| `SKIP_DIR_OUTPUT` | String | *None* | If set and `LOG_DIR` is not explicitly defined, automatically redirects logs to `<PERSIST_DIR>/logs/app.log`. |

---

## 🌐 BioWorker Server & Network Settings

These variables configure connectivity and authentication with the BioWorker execution backend:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `API_URL` | String (URL) | `http://localhost:8000` | Base URL of the BioWorker execution API server. Can also be defined under the `bioAG.API_URL` field in `config.yaml`. |
| `API_KEY` | String | `""` | Authentication key required to access the BioWorker API. Can also be defined under `bioAG.API_KEY` in `config.yaml`. |
| `PROJECT_ID` | String | *Auto-generated* | Active project session ID on BioWorker. If empty, BioGAIP creates a new project session and updates this variable dynamically. |
| `WORK_DIR` | String (Path) | `/data/work_dir` or current working directory | Target working directory where commands, scripts, and workflows are executed on the worker. Can also be configured via `bioWorker.WORK_DIR` in `config.yaml`. |
| `HTTPS_PROXY` | String (URL) | *None* | HTTP/HTTPS proxy address used for network requests. |

---

## 📚 RAG & Vector Memory Databases

BioGAIP utilizes ChromaDB persistent stores for various specialized retrieval-augmented generation (RAG) pipelines:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `CONDA_META_DATABASE` | String (Directory Path) | `/data/conda_meta` (or `~/.chromadb_autogen.conda_meta1`) | Directory path to the ChromaDB database containing Conda package metadata and environment definitions. |
| `WORKFLOW_DATABASE` | String (Directory Path) | `/data/pipelines_meta` (or `~/.all-MiniLM-embedding.chromadb_autogen.nfcore2`) | Directory path to the ChromaDB vector database containing Nextflow / nf-core pipeline templates and metadata. |
| `USER_EXT_DATABASE` | String (Directory Path) | `/data/user_ext` | Path to a local directory containing custom user literature/documents (`.pdf`, `.txt`, `.md`, `.markdown`, `.html`). All documents are parsed, chunked, and loaded into the vector memory at startup. |

---

## 🛠️ Tool & Custom Extension Controls

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `SKIP_CUSTOM_TOOL` | String (`"true"` / `"false"`) | `"false"` | When set to `"true"`, skips loading local custom tools defined in `tool_config.yaml` and `system_config.yaml`. |
| `SKIP_REMOTE_CUSTOM_TOOL` | String (`"true"` / `"false"`) | `"false"` | When set to `"true"`, skips loading and embedding remote tool specifications into agent memory. |

---

## 🖥️ UI, Formatting & Execution Output

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `MARKDOWN_RENDERER` | String (`"TRUE"` / `"FALSE"`) | `"TRUE"` | Wraps truncated shell/script outputs in Markdown code blocks (`···`) for enhanced UI readability. |
| `MAX_LINES` | Integer | `10` | Maximum number of output lines to display before truncation. For directory listing commands (`ls`, `ll`), this limit is automatically raised to at least `100`. |
| `SKIP_MODEL_CONTEXT` | String (`"True"` / `"False"`) | `"False"` | When set to `"True"` (or enabled via `skip_params_model_context` in configuration), omits certain model parameter context when loading agents. |

---

## ⚠️ Deprecated Variables

- **`ASK_EXEC`**: **Deprecated.** Manual user confirmation prompts prior to command execution have been superseded by platform-native approval workflows. Setting this variable will no longer have any effect.