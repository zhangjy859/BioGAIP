### Installation Methods

BioGAIP is designed to offer maximum flexibility with various installation methods, ensuring cross-platform compatibility and a low barrier to entry. You can install BioGAIP using any of the following approaches:

- **BioLauncher (Recommended)**: A cross-platform application featuring a comprehensive graphical user interface (GUI) and robust customization options. This is the highly recommended method for end-users.

- **Container Deployment**: Detailed in the subsequent chapters.

- **Running from Source**: Ideal for development, debugging, or highly customized scenarios. This method involves downloading the source code and running individual components manually. The general steps are as follows:

    1. Clone the BioGAIP repository from GitHub:
    ```bash
    git clone https://github.com/zhangjy859/BioGAIP
    cd BioGAIP
    ```

    2. Locate the core components within the source directory:
    ```text
    env/bioGen_env_mini.yaml            # BioGAIP execution environment (for Conda)
    env/bioGen_env_mini.txt             # BioGAIP execution environment (for pip)
    bioGen/web_v2/app3.py                  # BioAG main program
    biolancher/script/windows_gui_v2       # BioLauncher main program directory
    bioGen/docker/bioWorker/web_shell      # BioWorker main program directory
    ```

    3. Build the runtime environment using Conda or pip:
    
    *Using Conda:*
    ```bash
    conda env create -n biogaip-env -f env/bioGen_env_mini.yaml
    conda activate biogaip-env
    ```
    
    *Or using pip:*
    ```bash
    pip install -r env/bioGen_env_mini.txt
    ```

    4. Run the components. Each module has a specific execution command:
    
        **BioAG:**
        ```bash
        streamlit run bioGen/web_v2/app3.py --server.port 8501
        ```
        
        **BioWorker:**
        ```bash
        python bioGen/docker/bioWorker/web_shell/web_shell_command_v8.py
        ```
        
        **BioLauncher:** Please refer to the documentation inside the `biolancher/script/windows_gui_v2` directory.

- **Installing via Pip Package**

    1. Clone the BioGAIP repository:
    ```bash
    git clone https://github.com/zhangjy859/BioGAIP
    ```

    2. Install the package using pip:
    ```bash
    pip install ./BioGAIP/bioGen/pip_packages
    ```

    3. Once installed, you can access BioGAIP via the command-line interface (CLI):
    ```text
    biogaip --help
    
    usage: biogaip [-h] [--max-chat-message MAX_CHAT_MESSAGE] [--persist-dir PERSIST_DIR] [--log-dir LOG_DIR] [--skip-dir-output]
                   [--system-config-path SYSTEM_CONFIG_PATH] [--system-config-yaml-path SYSTEM_CONFIG_YAML_PATH] [--ask-exec {True,False,true,false}]
                   [--markdown-renderer {True,False,TRUE,FALSE}] [--conda-meta-database CONDA_META_DATABASE] [--workflow-database WORKFLOW_DATABASE]
                   [--user-ext-database USER_EXT_DATABASE] [--work-dir WORK_DIR] [--api-url API_URL] [--api-key API_KEY] [--skip-custom-tool]
                   [--skip-remote-custom-tool] [--skip-model-context {True,False,true,false}] [-p PORT]
                   {chainlit,streamlit,run} ...

    positional arguments:
      {chainlit,streamlit,run}

    options:
      -h, --help                                    show this help message and exit
      --max-chat-message MAX_CHAT_MESSAGE
      --persist-dir PERSIST_DIR
      --log-dir LOG_DIR
      --skip-dir-output
      --system-config-path SYSTEM_CONFIG_PATH
      --system-config-yaml-path SYSTEM_CONFIG_YAML_PATH
      --ask-exec {True,False,true,false}
      --markdown-renderer {True,False,TRUE,FALSE}
      --conda-meta-database CONDA_META_DATABASE
      --workflow-database WORKFLOW_DATABASE
      --user-ext-database USER_EXT_DATABASE
      --work-dir WORK_DIR
      --api-url API_URL
      --api-key API_KEY
      --skip-custom-tool
      --skip-remote-custom-tool
      --skip-model-context {True,False,true,false}
      -p PORT, --port PORT
    ```