import os
import random
import string
import subprocess
import time
from settings import CONTAINER_IMAGE, TARGET_BIOAGVARSION, SCRIPT_DIR, CACHE_PATH, MOUNT_BASE, ENCRYPTION_KEY, CONFIG_JSON, BUILD_DOCKER_FROM_SOURCE, parse_bio_config
from system_utils import run_cmd_with_output, download_file, convert_to_docker_host_path

def check_native_docker():
    try: return subprocess.check_output(["docker", "--version"]) is not None
    except Exception: return False

def check_wsl_docker():
    try: return subprocess.check_output(["wsl", "docker", "--version"]) is not None
    except Exception: return False

def check_wsl_ubuntu():
    try: return "Ubuntu" in subprocess.check_output(["wsl", "cat", "/etc/os-release"], text=True)
    except Exception: return False

def get_docker_prefix():
    if check_native_docker(): return ["docker"]
    if check_wsl_docker(): return ["wsl", "docker"]
    return None

def get_running_bioag_containers(docker_prefix):
    try:
        out = subprocess.check_output(docker_prefix + ["ps", "--format", '{{.Names}}'], text=True)
        return [n.strip() for n in out.splitlines() if n.strip() in ['bioag'] or n.startswith('bioag_')]
    except Exception: return []

def check_image_exists(docker_prefix):
    if not docker_prefix: return False
    try: return bool(subprocess.check_output(docker_prefix + ["images", "-q", CONTAINER_IMAGE]).strip())
    except Exception: return False

def build_image_if_needed(docker_prefix, output_queue=None):
    def log(msg, pfx=""): output_queue.put(f"{pfx}{msg}") if output_queue else None

    image_exists = check_image_exists(docker_prefix)
    version_match = False

    if image_exists:
        try:
            env_out = subprocess.check_output(docker_prefix + ["inspect", CONTAINER_IMAGE], text=True)
            cfg = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY)
            version_match = cfg['BioAG']['version'] in env_out
        except Exception: version_match = False

    if not image_exists or not version_match:
        cfg = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY)
        bioag_tag, bioag_url = cfg['BioAG']['tag'], cfg['BioAG']['update_url']

        if not BUILD_DOCKER_FROM_SOURCE:
            try:
                log(f"Pulling {bioag_tag}...")
                run_cmd_with_output(docker_prefix + ["pull", bioag_tag], output_queue, timeout=900)
                run_cmd_with_output(docker_prefix + ["tag", bioag_tag, CONTAINER_IMAGE], output_queue, timeout=100)
                return
            except Exception as e: log(f"Pull failed: {e}. Building from source...", "WARN: ")

        tar_path = os.path.join(SCRIPT_DIR, 'bioag_latest.tar.gz')
        download_file(bioag_url, tar_path, output_queue=output_queue)

        if os.path.exists(tar_path):
            try:
                wsl_path = f"/mnt/{tar_path[0].lower()}/{tar_path[3:].replace('\\', '/')}" if "wsl" in docker_prefix and os.name == 'nt' else tar_path
                run_cmd_with_output(docker_prefix + ["load", "-i", wsl_path], output_queue)
                os.remove(tar_path)
                return
            except Exception as e:
                if os.path.exists(tar_path): os.remove(tar_path)
                raise e

def start_docker(params, docker_prefix, output_queue, container_name):
    output_queue.put(("STATUS", 1, "RUNNING", "Preparing Configurations..."))
    mounts, envs = [], []
    
    path_map = {
        params.get('configure'): "/config/system_config.yaml:ro",
        params.get('conda_meta'): f"{MOUNT_BASE}/conda_meta:rw",
        params.get('workflow'): f"{MOUNT_BASE}/pipelines_meta:rw",
        params.get('user_ext'): f"{MOUNT_BASE}/user_ext:rw"
    }
    for host_path, cont_path in path_map.items():
        if host_path: mounts.extend(["-v", f"{convert_to_docker_host_path(host_path, docker_prefix)}:{cont_path}"])

    cache = params.get('cache')
    if cache:
        host = convert_to_docker_host_path(cache, docker_prefix)
        mounts.extend(["-v", f"{host}:/cache", "-v", f"{host}:/home/mambauser/.cache", "-v", f"{host}/user_sessions{params['random_key']}:/app/user_sessions"])
    
    res_cache = params.get('res_cache') or cache
    if res_cache: mounts.extend(["-v", f"{convert_to_docker_host_path(res_cache, docker_prefix)}:/runtime"])

    if params.get('user_name') and params.get('user_password'): envs.extend(["-e", f"APP_USER={params['user_name']}:{params['user_password']}"])
    if params.get('proxy'): envs.extend(["--env", f"http_proxy={params['proxy']}", "--env", f"https_proxy={params['proxy']}"])
    if params.get('gemini_mode'): envs.extend(["-e", "SKIP_MODEL_CONTEXT=true"])
    if params.get('allow_network'): envs.extend(["--env", "ALLOW_NETWORK=1"])
    if params.get('local_storage') == 'SQLite': envs.extend(["-e", "USE_SQLITE=true"])
    
    envs.extend(['-e', 'PERSIST_DIR=/app/user_sessions'])
    gpus = ["--gpus", "all"] if params.get('enable_gpu') else []
    ports = ["-p", f"{params['bioag_port']}:8501"] if params['front_ui'] == "streamlit" else []
    
    cmd_args = [params['front_ui']] if params['front_ui'] != "CLI" else []
    output_queue.put(("STATUS", 1, "SUCCESS", "Configurations Prepared"))
    output_queue.put(("STATUS", 2, "RUNNING", "Starting Docker Container..."))

    cmd = docker_prefix + ["run", "-d", "--rm", "--name", container_name] + ports + ["--security-opt=no-new-privileges"] + gpus + mounts + envs + [CONTAINER_IMAGE] + cmd_args
    try:
        subprocess.check_call(cmd)
        time.sleep(3)
        subprocess.check_call(docker_prefix + ["ps", '-a', '|', 'grep', '-q', container_name])
        output_queue.put(("STATUS", 2, "SUCCESS", "Container Started Successfully"))
    except Exception as e:
        output_queue.put(("STATUS", 2, "ERROR", "Failed to Start Container"))
        output_queue.put("DONE")
        return

    output_queue.put(("STATUS", 3, "RUNNING", "Waiting for Services Initialization..."))
    log_proc = subprocess.Popen(docker_prefix + ["logs", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    success = False
    start_time = time.time()
    while time.time() - start_time < 1600:
        line = log_proc.stdout.readline()
        if line:
            output_queue.put(line.strip())
            if "URL" in line:
                success = True
                break
        time.sleep(0.1)

    log_proc.terminate()
    output_queue.put(("STATUS", 3, "SUCCESS" if success else "ERROR", "Services Initialized" if success else "Initialization Failed"))
    output_queue.put("DONE")
    output_queue.put(f"SUCCESS:{success}")

def stop_container_task(docker_prefix, container_name, output_queue):
    output_queue.put(("STATUS", 1, "RUNNING", f"Locating Container '{container_name}'..."))
    try:
        if subprocess.check_output(docker_prefix + ["ps", "-q", "--filter", f"name=^{container_name}$"], text=True).strip():
            output_queue.put(("STATUS", 1, "SUCCESS", "Container Found"))
            output_queue.put(("STATUS", 2, "RUNNING", "Stopping Container..."))
            subprocess.check_call(docker_prefix + ["stop", container_name])
            output_queue.put(("STATUS", 2, "SUCCESS", "Container Stopped"))
            output_queue.put(("STATUS", 3, "RUNNING", "Removing Container..."))
            subprocess.call(docker_prefix + ["rm", container_name])
            output_queue.put(("STATUS", 3, "SUCCESS", "Container Removed Successfully"))
        else:
            for i in range(1, 4): output_queue.put(("STATUS", i, "SKIPPED", "Skipped"))
    except Exception as e:
        output_queue.put(("STATUS", 1, "ERROR", f"Error: {e}"))
    output_queue.put("DONE")