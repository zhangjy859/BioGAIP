import os
import sys
import argparse
import subprocess
from dotenv import load_dotenv

def ensure_playwright():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception:
        print("Installing playwright dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"]
        )

def main():
    if os.path.exists(".env"):
        load_dotenv(".env")
        
    parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]))
    
    parser.add_argument("--max-chat-message", type=str)
    parser.add_argument("--persist-dir", type=str)
    parser.add_argument("--log-dir", type=str)
    parser.add_argument("--skip-dir-output", action="store_true")
    parser.add_argument("--system-config-path", type=str)
    parser.add_argument("--system-config-yaml-path", type=str)
    parser.add_argument("--ask-exec", type=str, choices=["True", "False", "true", "false"])
    parser.add_argument("--markdown-renderer", type=str, choices=["True", "False", "TRUE", "FALSE"])
    parser.add_argument("--conda-meta-database", type=str)
    parser.add_argument("--workflow-database", type=str)
    parser.add_argument("--user-ext-database", type=str)
    parser.add_argument("--work-dir", type=str)
    parser.add_argument("--api-url", type=str)
    parser.add_argument("--api-key", type=str)
    parser.add_argument("--skip-custom-tool", action="store_true")
    parser.add_argument("--skip-remote-custom-tool", action="store_true")
    parser.add_argument("--skip-model-context", type=str, choices=["True", "False", "true", "false"])
    parser.add_argument("-p", "--port", type=str, default="8501")

    subparsers = parser.add_subparsers(dest="command")
    
    chainlit_parser = subparsers.add_parser("chainlit")
    chainlit_parser.add_argument("-p", "--port", type=str, default="8501")
    
    streamlit_parser = subparsers.add_parser("streamlit")
    streamlit_parser.add_argument("-p", "--port", type=str, default="8501")
    
    streamlit_parser = subparsers.add_parser("run")
    streamlit_parser.add_argument("-p", "--port", type=str, default="8501")
    
    
    args = parser.parse_args()

    env_mapping = {
        "MAX_CHAT_MESSAGE": args.max_chat_message,
        "PERSIST_DIR": args.persist_dir,
        "LOG_DIR": args.log_dir,
        "SYSTEM_CONFIG_PATH": args.system_config_path,
        "SYSTEM_CONFIG_YAML_PATH": args.system_config_yaml_path,
        "ASK_EXEC": args.ask_exec,
        "MARKDOWN_RENDERER": args.markdown_renderer,
        "CONDA_META_DATABASE": args.conda_meta_database,
        "WORKFLOW_DATABASE": args.workflow_database,
        "USER_EXT_DATABASE": args.user_ext_database,
        "WORK_DIR": args.work_dir,
        "API_URL": args.api_url,
        "API_KEY": args.api_key,
        "SKIP_MODEL_CONTEXT": args.skip_model_context,
    }

    for key, value in env_mapping.items():
        if value is not None:
            os.environ[key] = str(value)

    if args.skip_dir_output:
        os.environ["SKIP_DIR_OUTPUT"] = "true"
    if args.skip_custom_tool:
        os.environ["SKIP_CUSTOM_TOOL"] = "true"
    if args.skip_remote_custom_tool:
        os.environ["SKIP_REMOTE_CUSTOM_TOOL"] = "true"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    _ = ensure_playwright()

    if args.command == "chainlit":
        ## warning: Deprecated functions
        logger.warning("The 'chainlit' command is deprecated. Please use 'streamlit' instead.")
        sleep(3)
        target = os.path.join(base_dir, "web", "app_chainlit1.py")
        subprocess.run(["chainlit", "run", target, "--port", args.port])
    elif args.command == "streamlit":
        target = os.path.join(base_dir, "web_v2", "app3.py")
        subprocess.run(["streamlit", "run", target, "--server.port", args.port])
    elif args.command is None:
        target = os.path.join(base_dir, "web_v2", "app3.py")
        subprocess.run(["streamlit", "run", target, "--server.port", args.port])
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()