import os
import sys
import time
import random
import string
import subprocess
import streamlit as st

from constants import (CONTAINER_IMAGE, CONTAINER_NAME, TARGET_BIOAGVARSION, 
                       MOUNT_BASE, cache_path, script_dir, build_docker_from_source, 
                       ENCRYPTION_KEY, CONFIG_JSON)
from utils import run_cmd_with_output, download_file, parse_bio_config, write_to_debug_file

def check_native_docker():
    try:
        subprocess.check_output(["docker", "--version"])
        return True
    except: return False

def check_wsl_docker():
    try:
        subprocess.check_output(["wsl", "docker", "--version"])
        return True
    except: return False

def check_wsl_ubuntu():
    try:
        output = subprocess.check_output(["wsl", "cat", "/etc/os-release"], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        if "Ubuntu" in output:
            return True
    except: pass
    return False

def get_docker_prefix():
    if check_native_docker(): return ["docker"]
    elif check_wsl_docker(): return ["wsl", "docker"]
    else: return None

def convert_to_docker_host_path(path, docker_prefix):
    if not path.startswith("~"):
        path = os.path.abspath(path)
    print("Converting path:", path, file=sys.stderr)
    if path.startswith('/mnt') or path.startswith("~"):
        return path
    if "wsl" in docker_prefix:
        if path.startswith("/"): return path
        if os.name == 'nt':
            drive, rest = os.path.splitdrive(path)
            if drive:
                drive = drive.lower().replace(':', '')
                rest = rest.replace('\\', '/').lstrip('/')
                return f'/mnt/{drive}/{rest}'
    return path

def get_running_bioag_containers(docker_prefix):
    try:
        output = subprocess.check_output(docker_prefix + ["ps", "--format", '"{{.Names}}"'])
        names = [n.strip().replace("\"", "") for n in output.decode().split('\n') if n.strip()]
        bioag_names = [n for n in names if n == 'bioag' or n.startswith('bioag_')]
        sys.stderr.write(f"{len(bioag_names)} running bioag container(s) found: {bioag_names}\n")
        return bioag_names
    except Exception as e:
        sys.stderr.write(f"Error checking running containers: {e}\n")
        return []

def check_image_exists(docker_prefix):
    if not docker_prefix: return False
    try:
        output = subprocess.check_output(docker_prefix + ["images", "-q", CONTAINER_IMAGE], stderr=subprocess.DEVNULL)
        return bool(output.strip())
    except Exception: return False

def build_image_if_needed(docker_prefix, output_queue=None):
    def log_info(msg): output_queue.put(msg) if output_queue else st.info(msg)
    def log_success(msg): output_queue.put(msg) if output_queue else st.success(msg)
    def log_warning(msg): output_queue.put(f"WARN: {msg}") if output_queue else st.warning(msg)
    def log_error(msg): output_queue.put(f"ERR: {msg}") if output_queue else st.error(msg)
        
    try:
        output = subprocess.check_output(docker_prefix + ["images", "-q", CONTAINER_IMAGE], stderr=subprocess.DEVNULL)
        image_exists = bool(output.strip())

        log_warning('Cheaking Local image version')
        version_match = False
        if image_exists:
            try:
                inspect_cmd = docker_prefix + ["inspect", CONTAINER_IMAGE]
                env_output = subprocess.check_output(inspect_cmd, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
                bioag_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
                try: TARGET_BIOAGVARSION_VALUE = bioag_config['BioAG']['version']
                except Exception as e:
                    log_warning(f"Failed to get target version, using default {TARGET_BIOAGVARSION}. Error: {e}")
                    TARGET_BIOAGVARSION_VALUE = TARGET_BIOAGVARSION
                version_match = TARGET_BIOAGVARSION_VALUE in env_output
                log_info(f"Local image version check: {'✅ MATCH' if version_match else '❌ MISMATCH'}")
            except Exception as e:
                log_warning(f"Could not read image env: {e}")
                version_match = False

        if not image_exists or not version_match:
            log_warning("Image not found or version mismatch. Checking BioAG configuration...")
            bioag_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
            bioag_tag = bioag_config['BioAG']['tag']
            bioag_url = bioag_config['BioAG']['update_url']
            write_to_debug_file(f"BioAG tag: {bioag_tag}, {bioag_url}")
            
            if not build_docker_from_source:
                try:
                    log_info(f"Pulling from registry...")
                    run_cmd_with_output(docker_prefix + ["pull", f"{bioag_tag}"], output_queue, timeout=900)
                    run_cmd_with_output(docker_prefix + ["tag", f"{bioag_tag}", CONTAINER_IMAGE], output_queue, timeout=100)
                    log_success(f"Image pulled and tagged successfully.")
                    return
                except Exception as e:
                    log_warning(f"Pull failed. Will build from source. Error: {e}")

            log_info(f"Downloading and building from source...")
            tar_path = os.path.join(script_dir, 'bioag_latest.tar.gz')
            try: download_file(bioag_url, tar_path, output_queue=output_queue)
            except Exception as e: log_warning(f"Download failed: {e}")

            if os.path.exists(tar_path):
                try: 
                    log_info("Loading image from bioag_latest.tar.gz...")
                    def windows_to_wsl_path(win_path: str) -> str:
                        if os.name != 'nt' or len(win_path) < 3 or win_path[1] != ':' or win_path[2] != '\\': return win_path
                        drive = win_path[0].lower()
                        path = win_path[3:].replace('\\', '/')
                        return f"/mnt/{drive}/{path}" if path else f"/mnt/{drive}/"

                    wsl_tar_path = windows_to_wsl_path(tar_path) if "wsl" in docker_prefix else tar_path
                    run_cmd_with_output(docker_prefix + ["load", "-i", wsl_tar_path], output_queue)
                    log_success(f"Image loaded successfully from tar.gz.")
                    if os.path.exists(tar_path):
                        os.remove(tar_path)
                        log_info(f"Removed temporary tar file.")
                    return
                except Exception as e:
                    if os.path.exists(tar_path): os.remove(tar_path)
                    log_error(f"Failed to load image from tar.gz: {e}")
                    raise e
                    
            repo_url = "xxx"
            if repo_url == "xxx":
                log_error("Git repo URL not configured. Cannot build from source.")
                return

            tmpdir_name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            tmpdir = os.path.join(cache_path, tmpdir_name)
            os.makedirs(tmpdir, exist_ok=True)
            cwd = os.getcwd()
            os.chdir(tmpdir)
            run_cmd_with_output(["git", "clone", repo_url], output_queue)
            repo_name = repo_url.split('/')[-1].rstrip('.git')
            os.chdir(f"{repo_name}/docker")
            context = convert_to_docker_host_path(os.getcwd(), docker_prefix)
            run_cmd_with_output(docker_prefix + ["build", "-t", CONTAINER_IMAGE, context], output_queue)
            os.chdir(cwd)
            log_success(f"Image built successfully from source.")
        else:
            log_success(f"Image {CONTAINER_IMAGE} already exists with correct version.")
    except Exception as e:
        log_error(f"Error checking or building image: {e}")

def start_docker_demo(docker_prefix, output_queue):
    if "wsl" not in docker_prefix:
        output_queue.put("Demo mode is only required with WSL Docker. skipping...")
        return
    command = ['wsl', '-u', 'root', 'service', 'docker', 'start']
    try:
        subprocess.check_call(command)
        output_queue.put("Docker service started successfully in WSL.")
    except Exception as e:
        output_queue.put(f"Error starting Docker service in WSL: {e}")

def start_docker(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, enable_gpu, docker_prefix,
                 output_queue, user_name="admin", user_password="admin", gemini_mode=False, port=8501, 
                 container_name=CONTAINER_NAME, res_cache = None, random_key = '', allow_network = False, local_storage = 'File System (Json)'):
    output_queue.put(("STATUS", 1, "RUNNING", "Preparing Configurations..."))
    mounts = []
    if configure:
        host = convert_to_docker_host_path(configure, docker_prefix)
        mounts.extend(["-v", f"{host}:/config/system_config.yaml:ro"])
    if conda_meta: mounts.extend(["-v", f"{convert_to_docker_host_path(conda_meta, docker_prefix)}:{MOUNT_BASE}/conda_meta:rw"])
    if workflow: mounts.extend(["-v", f"{convert_to_docker_host_path(workflow, docker_prefix)}:{MOUNT_BASE}/pipelines_meta:rw"])
    if user_ext: mounts.extend(["-v", f"{convert_to_docker_host_path(user_ext, docker_prefix)}:{MOUNT_BASE}/user_ext:rw"])
    if cache:
        host = convert_to_docker_host_path(cache, docker_prefix)
        mounts.extend(["-v", f"{host}:/cache", "-v", f"{host}:/home/mambauser/.cache", "-v", f"{host}/user_sessions{random_key}:/app/user_sessions"])
    if res_cache: mounts.extend(["-v", f"{convert_to_docker_host_path(res_cache, docker_prefix)}:/runtime"])
    elif cache: mounts.extend(["-v", f"{convert_to_docker_host_path(cache, docker_prefix)}:/runtime"])
    if user_name and user_password: mounts.extend(["-e", f"APP_USER={user_name}:{user_password}"])
    
    envs = []
    if proxy: envs.extend(["--env", f"http_proxy={proxy}", "--env", f"https_proxy={proxy}"])
    if gemini_mode: envs.extend(["-e", "SKIP_MODEL_CONTEXT=true"])
    if allow_network: envs.extend(["--env", "ALLOW_NETWORK=1"])
    if local_storage == 'SQLite': envs.extend(["-e", "USE_SQLITE=true"])
    envs.extend(['-e', 'PERSIST_DIR=/app/user_sessions'])
    
    gpus = ["--gpus", "all"] if enable_gpu else []
    ports = ["-p", f"{port}:8501"] if front_ui == "streamlit" else []
    safetly_args = '--security-opt=no-new-privileges'
    cmd_args = [front_ui] if front_ui != "CLI" else []
        
    output_queue.put(("STATUS", 1, "SUCCESS", "Configurations Prepared"))
    output_queue.put(("STATUS", 2, "RUNNING", "Starting Docker Container..."))

    command = docker_prefix + ["run", "-d", "--rm", "--name", container_name] + ports + [safetly_args] + gpus + mounts + envs + [CONTAINER_IMAGE] + cmd_args
    sys.stderr.write(" ".join(command) + "\n")
    try:
        subprocess.check_call(command)
        time.sleep(3)
        subprocess.check_call(docker_prefix + ["ps", '-a', '|', 'grep', '-q', container_name])
        output_queue.put(("STATUS", 2, "SUCCESS", "Container Started Successfully"))
    except Exception as e:
        output_queue.put(("STATUS", 2, "ERROR", "Failed to Start Container"))
        output_queue.put(f"Error starting container: {e}\nCommand line: {' '.join(command)}")
        output_queue.put("DONE")
        return
        
    output_queue.put(("STATUS", 3, "RUNNING", "Waiting for Services Initialization... (~ 10 - 30 minutes for first launcher)"))
    log_command = docker_prefix + ["logs", "-f", container_name]
    log_process = subprocess.Popen(log_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    success = False
    start_time = time.time()
    
    while (time.time() - start_time) < 1600:
        line = log_process.stdout.readline()
        if line:
            output_queue.put(line.strip())
            if "URL" in line:
                success = True
                break
        time.sleep(0.1)
        
    log_process.terminate()
    log_process.wait()
    
    if success: output_queue.put(("STATUS", 3, "SUCCESS", "Services Initialized & Ready"))
    else:
        output_queue.put(("STATUS", 3, "ERROR", "Initialization Failed or Timeout"))
        err = log_process.stderr.read()
        if err: output_queue.put(f"Log error: {err}")
        
    output_queue.put("DONE")
    output_queue.put(f"SUCCESS:{success}")

def stop_container_task(docker_prefix, container_name, output_queue):
    output_queue.put(("STATUS", 1, "RUNNING", f"Locating Container '{container_name}'..."))
    try:
        output = subprocess.check_output(docker_prefix + ["ps", "-q", "--filter", f"name=^{container_name}$"])
        if output.strip():
            output_queue.put(("STATUS", 1, "SUCCESS", "Container Found"))
            output_queue.put(("STATUS", 2, "RUNNING", "Stopping Container..."))
            subprocess.check_call(docker_prefix + ["stop", container_name])
            output_queue.put(("STATUS", 2, "SUCCESS", "Container Stopped"))
            
            output_queue.put(("STATUS", 3, "RUNNING", "Removing Container..."))
            try: subprocess.check_call(docker_prefix + ["rm", container_name])
            except: output_queue.put(("STATUS", 1, "ERROR", "Removing Container Fail..."))
            output_queue.put(("STATUS", 3, "SUCCESS", "Container Removed Successfully"))
        else:
            output_queue.put(("STATUS", 1, "SKIPPED", "No Running Container Found"))
            output_queue.put(("STATUS", 2, "SKIPPED", "Stop Skipped"))
            output_queue.put(("STATUS", 3, "SKIPPED", "Remove Skipped"))
    except Exception as e:
        output_queue.put(("STATUS", 1, "ERROR", "Error During Termination"))
        output_queue.put(f"Error stopping container: {e}")
    output_queue.put("DONE")