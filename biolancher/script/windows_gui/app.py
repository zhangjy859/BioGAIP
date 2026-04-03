# app.py - Streamlit application for Windows
import re
import string
import random
import streamlit as st
import subprocess
import os
import sys
import tempfile
import shutil
import threading
import queue
import io
import time
import yaml
import requests
import signal
import tarfile
import atexit
import socket
import psutil
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Union, Optional
import base64
import json
from urllib.request import urlopen
from urllib.error import URLError
import ssl
import certifi
import platform
from streamlit.runtime.scriptrunner import add_script_run_ctx

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "0") == "1"
# Container configuration
CONTAINER_IMAGE = "bioag:latest"
CONTAINER_NAME = "bioag"
TARGET_BIOAGVARSION = "1.3.0.10"
MOUNT_BASE = "/data"
cache_path = os.environ.get("BIOGEN_CACHE", os.path.expanduser("~/.cache/bioag"))
if not os.path.exists(cache_path):
    os.makedirs(cache_path)
# Script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
micromamba_path = os.path.join(script_dir, 'micromamba.exe')
envs_dir = os.path.join(script_dir, 'envs')
biogen_env = os.path.join(envs_dir, 'biogen')
env_yaml = os.path.join(script_dir, 'envs', 'env.yaml')
installed_flag = os.path.join(biogen_env, ".installed")
ENCRYPTION_KEY = 'xD7WU2JVDrQal9'
CONFIG_JSON = "https://dataweb.biogaip.top/server_aws.config?expires=10414438925&token=42e159c5957d860b45685afb9eedd87d778a403dbd417c228b0624b3b9981249"

def inject_dialog_style():
    """Injects CSS to prevent closing the dialog by clicking outside of it, while retaining the top-right 'X' button."""
    st.markdown("""
    <style>
    /* Prevent closing when clicking outside the dialog by disabling pointer events on the backdrop */
    div[data-testid="stModal"] > div:first-child { 
        pointer-events: none !important; 
    }
    
    /* Disable clicks on the main app background to prevent interacting with the app while modal is active */
    .stApp:has(div[data-testid="stModal"]) { 
        pointer-events: none !important; 
    }
    
    /* Safely re-enable clicks inside the dialog so content and the 'X' remain fully functional */
    div[role="dialog"] { 
        pointer-events: auto !important; 
    }
    
    @keyframes step-pulse {
        0% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(0, 123, 255, 0); }
        100% { box-shadow: 0 0 0 0 rgba(0, 123, 255, 0); }
    }
    </style>
    """, unsafe_allow_html=True)

def render_step(container, state="PENDING", text=""):
    icon = "⚪"
    color = "#6c757d"
    bg_color = "transparent"
    border_color = "rgba(128, 128, 128, 0.2)"
    animation = ""
    
    if state == "RUNNING":
        icon = "⏳"
        color = "#007BFF"
        bg_color = "rgba(0, 123, 255, 0.05)"
        border_color = "#007BFF"
        animation = "animation: step-pulse 1.5s infinite;"
    elif state == "SUCCESS":
        icon = "✅"
        color = "#28A745"
        bg_color = "rgba(40, 167, 69, 0.05)"
        border_color = "#28A745"
    elif state == "SKIPPED":
        icon = "❗"
        color = "#FD7E14"
        bg_color = "rgba(253, 126, 20, 0.05)"
        border_color = "#FD7E14"
    elif state == "ERROR":
        icon = "❌"
        color = "#DC3545"
        bg_color = "rgba(220, 53, 69, 0.05)"
        border_color = "#DC3545"

    html = f"""
    <div style="padding: 14px 18px; margin: 10px 0; border-radius: 10px; border: 1px solid {border_color}; background-color: {bg_color}; display: flex; align-items: center; transition: all 0.3s ease; {animation}">
        <span style="font-size: 1.5em; margin-right: 18px; line-height: 1;">{icon}</span>
        <span style="color: {color}; font-weight: 600; font-size: 1.1em; letter-spacing: 0.2px;">{text}</span>
    </div>
    """
    container.markdown(html, unsafe_allow_html=True)

def check_native_docker():
    try:
        subprocess.check_output(["docker", "--version"])
        return True
    except:
        return False

def check_wsl_docker():
    try:
        subprocess.check_output(["wsl", "docker", "--version"])
        return True
    except:
        return False

def check_wsl_ubuntu():
    try:
        output = subprocess.check_output(["wsl", "cat", "/etc/os-release"], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        if "Ubuntu" in output:
            return True
    except:
        pass
    return False

def get_docker_prefix():
    if check_native_docker():
        return ["docker"]
    elif check_wsl_docker():
        return ["wsl", "docker"]
    else:
        return None

def convert_to_docker_host_path(path, docker_prefix):
    if not path.startswith("~"):
        path = os.path.abspath(path)
    print("Converting path:", path, file=sys.stderr)
    if path.startswith('/mnt') or path.startswith("~"):
        return path
    if "wsl" in docker_prefix:
        if path.startswith("/"):
            return path
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
        ## decode output 
        names = [n.strip().replace("\"", "") for n in output.decode().split('\n') if n.strip()]
        bioag_names = [n for n in names if n == 'bioag' or n.startswith('bioag_')]
        sys.stderr.write(f"{len(bioag_names)} running bioag container(s) found: {bioag_names} {names}, Check cmd is {" ".join(docker_prefix + ["ps", "--format", '"{{.Names}}"'])}, output: {output.decode()}\n")
        return bioag_names
    except Exception as e:
        sys.stderr.write(f"Error checking running containers: {e}\n")
        return []

def check_image_exists(docker_prefix):
    if not docker_prefix:
        return False
    try:
        output = subprocess.check_output(docker_prefix + ["images", "-q", CONTAINER_IMAGE], stderr=subprocess.DEVNULL)
        return bool(output.strip())
    except Exception:
        return False

#def run_cmd_with_output(cmd, output_queue=None):
#    if output_queue:
#        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
#        for line in iter(p.stdout.readline, ''):
#            if line:
#                output_queue.put(line.strip())
#        p.wait()
#        if p.returncode != 0:
#            raise Exception(f"Command '{' '.join(cmd)}' failed with exit code {p.returncode}")
#    else:
#        subprocess.check_call(cmd)
def run_cmd_with_output(cmd, output_queue=None, timeout=None):
    if output_queue:
        p = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            bufsize=1
        )
        
        is_timeout = False
        def kill_proc():
            nonlocal is_timeout
            is_timeout = True
            try:
                p.kill()
            except OSError:
                pass

        timer = None
        if timeout is not None:
            timer = threading.Timer(timeout, kill_proc)
            timer.start()

        try:
            for line in iter(p.stdout.readline, ''):
                if line:
                    output_queue.put(line.strip())
            p.wait()
        finally:
            if timer is not None:
                timer.cancel()

        if is_timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
            
        if p.returncode != 0:
            raise Exception(f"Command '{' '.join(cmd)}' failed with exit code {p.returncode}")
    else:
        subprocess.check_call(cmd, timeout=timeout)

def download_file(url: str, destination: Union[str, Path], chunk_size: int = 65536, output_queue=None) -> Optional[Path]:
    dest_path = Path(destination).resolve()
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(request) as response, dest_path.open('wb') as out_file:
            content_length = response.info().get('Content-Length')
            total_size = int(content_length) if content_length else None
            downloaded_size = 0
            
            #msg = f"Downloading from: {url}\nSaving to: {dest_path}"
            #if output_queue: output_queue.put(msg)
            #else: print(msg)
            
            last_reported_percent = -1
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded_size += len(chunk)
                
                if total_size:
                    percent = (downloaded_size / total_size) * 100
                    if int(percent) > last_reported_percent:
                        last_reported_percent = int(percent)
                        if output_queue and last_reported_percent % 5 == 0:
                            output_queue.put(f"Progress: [{percent:5.1f}%] {downloaded_size}/{total_size} bytes")
                        elif not output_queue:
                            sys.stdout.write(f"\rProgress: [{percent:5.1f}%] {downloaded_size}/{total_size} bytes")
                            sys.stdout.flush()
                else:
                    if output_queue:
                        if downloaded_size - (last_reported_percent * 1024 * 1024) > 1024 * 1024:
                            last_reported_percent = int(downloaded_size / (1024*1024))
                            output_queue.put(f"Progress: {downloaded_size} bytes downloaded")
                    else:
                        sys.stdout.write(f"\rProgress: {downloaded_size} bytes downloaded")
                        sys.stdout.flush()
            
            msg_done = "\nDownload completed successfully!\n"
            if output_queue: output_queue.put(msg_done.strip())
            else: sys.stdout.write(msg_done)
            return dest_path
            
    except urllib.error.URLError as e:
        msg = f"Network Error: Failed to download the file. ({e})"
        if output_queue: output_queue.put(f"ERR: {msg}")
        else: print(f"\n{msg}")
        return None
    except OSError as e:
        msg = f"File System Error: Could not save the file. ({e})"
        if output_queue: output_queue.put(f"ERR: {msg}")
        else: print(f"\n{msg}")
        return None

def build_image_if_needed(docker_prefix, output_queue=None):
    def log_info(msg):
        if output_queue: output_queue.put(msg)
        else: st.info(msg)
    def log_success(msg):
        if output_queue: output_queue.put(msg)
        else: st.success(msg)
    def log_warning(msg):
        if output_queue: output_queue.put(f"WARN: {msg}")
        else: st.warning(msg)
    def log_error(msg):
        if output_queue: output_queue.put(f"ERR: {msg}")
        else: st.error(msg)
        
    try:
        output = subprocess.check_output(docker_prefix + ["images", "-q", CONTAINER_IMAGE], stderr=subprocess.DEVNULL)
        image_exists = bool(output.strip())

        log_warning('Cheaking Local image version')
        version_match = False
        if image_exists:
            try:
                inspect_cmd = docker_prefix + [
                    "inspect",
                    CONTAINER_IMAGE
                ]
                env_output = subprocess.check_output(inspect_cmd, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
                version_match = TARGET_BIOAGVARSION in env_output
                sys.stderr.write(f"Image env output: {env_output}\n")
                log_info(f"Local image version check: {'✅ MATCH' if version_match else '❌ MISMATCH'}")
            except Exception as e:
                log_warning(f"Could not read image env (image may be corrupted): {e}")
                version_match = False

        if not image_exists or not version_match:
            ## find bioag configure
            log_warning("Image not found or version mismatch. Checking BioAG configuration...")
            bioag_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
            bioag_tag = bioag_config['BioAG']['tag']
            bioag_url = bioag_config['BioAG']['update_url']
            write_to_debug_file(f"BioAG tag: {bioag_tag}, {bioag_url}")
            if not build_docker_from_source:
                try:
                    log_info(f"Image {CONTAINER_IMAGE} not found or wrong version. Pulling from registry...")
                    #run_cmd_with_output(docker_prefix + ["pull", f"10.157.66.19:5000/{CONTAINER_IMAGE}"], output_queue)
                    run_cmd_with_output(docker_prefix + ["pull", f"{bioag_tag}"], output_queue, timeout=900)
                    run_cmd_with_output(docker_prefix + ["tag", f"{bioag_tag}", CONTAINER_IMAGE], output_queue, timeout=100)
                    log_success(f"Image {CONTAINER_IMAGE} pulled and tagged successfully.")
                    return
                except Exception as e:
                    log_warning(f"Pull failed. Will build from source. Error: {e}")

            log_info(f"Image {CONTAINER_IMAGE} not found or version mismatch. Downloading and building from source...")
            
            tar_path = os.path.join(script_dir, 'bioag_latest.tar.gz')
            # always download the latest tar.gz
            #if not os.path.exists(tar_path):
            try:
                download_file(bioag_url, tar_path, output_queue=output_queue)
            except Exception as e:
                log_warning(f"Download failed: {e}")

            if os.path.exists(tar_path):
                try: 
                    log_info("Loading image from bioag_latest.tar.gz...")
                    def windows_to_wsl_path(win_path: str) -> str:
                        if os.name != 'nt' or len(win_path) < 3 or win_path[1] != ':' or win_path[2] != '\\':
                            return win_path
                        drive = win_path[0].lower()
                        path = win_path[3:].replace('\\', '/')
                        return f"/mnt/{drive}/{path}" if path else f"/mnt/{drive}/"

                    wsl_tar_path = windows_to_wsl_path(tar_path) if "wsl" in docker_prefix else tar_path
                    run_cmd_with_output(docker_prefix + ["load", "-i", wsl_tar_path], output_queue)
                    log_success(f"Image {CONTAINER_IMAGE} loaded successfully from tar.gz.")
                    ## remove the tar file
                    if os.path.exists(tar_path):
                        os.remove(tar_path)
                        log_info(f"Removed temporary tar file: {tar_path}")
                    else:
                        log_warning(f"Temporary tar file not found: {tar_path}")
                    return
                except Exception as e:
                    if os.path.exists(tar_path):
                        os.remove(tar_path)
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
            docker_dir = os.getcwd()
            context = convert_to_docker_host_path(docker_dir, docker_prefix)
            run_cmd_with_output(docker_prefix + ["build", "-t", CONTAINER_IMAGE, context], output_queue)
            os.chdir(cwd)
            log_success(f"Image {CONTAINER_IMAGE} built successfully from source.")
        else:
            log_success(f"Image {CONTAINER_IMAGE} already exists with correct version {TARGET_BIOAGVARSION}.")

    except Exception as e:
        log_error(f"Error checking or building image: {e}")

safetly_args = '--cap-drop SETUID --cap-drop SETGID --security-opt=no-new-privileges'
bioag_port = 8501

def start_docker_demo(docker_prefix, output_queue):
    if "wsl" not in docker_prefix:
        output_queue.put("Demo mode is only required with WSL Docker. skipping...")
        return
    command = ['wsl', '-u', 'root', 'service', 'docker', 'start']
    sys.stderr.write(" ".join(command) + "\n")
    try:
        subprocess.check_call(command)
        output_queue.put("Docker service started successfully in WSL.")
    except Exception as e:
        output_queue.put(f"Error starting Docker service in WSL: {e}, \n Command line: {' '.join(command)}")
        return

def start_docker(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, enable_gpu, docker_prefix,
                 output_queue, user_name="admin", user_password="admin", gemini_mode=False, port=8501, container_name=CONTAINER_NAME, res_cache = None, random_key = '', allow_network = False):
    output_queue.put(("STATUS", 1, "RUNNING", "Preparing Configurations..."))
    mounts = []
    if configure:
        host = convert_to_docker_host_path(configure, docker_prefix)
        mounts.extend(["-v", f"{host}:/config/system_config.yaml:ro"])
    if conda_meta:
        host = convert_to_docker_host_path(conda_meta, docker_prefix)
        mounts.extend(["-v", f"{host}:{MOUNT_BASE}/conda_meta:rw"])
    if workflow:
        host = convert_to_docker_host_path(workflow, docker_prefix)
        mounts.extend(["-v", f"{host}:{MOUNT_BASE}/pipelines_meta:rw"])
    if user_ext:
        host = convert_to_docker_host_path(user_ext, docker_prefix)
        mounts.extend(["-v", f"{host}:{MOUNT_BASE}/user_ext:rw"])
    if cache:
        host = convert_to_docker_host_path(cache, docker_prefix)
        mounts.extend(["-v", f"{host}:/cache"])
        mounts.extend(["-v", f"{host}:/home/mambauser/.cache"])
        mounts.extend(["-v", f"{host}/user_sessions{random_key}:/app/user_sessions"])
    if res_cache:
        host = convert_to_docker_host_path(res_cache, docker_prefix)
        mounts.extend(["-v", f"{host}:/runtime"])
    elif cache:
        host = convert_to_docker_host_path(cache, docker_prefix)
        mounts.extend(["-v", f"{host}:/runtime"])
    if user_name and user_password:
        mounts.extend(["-e", f"APP_USER={user_name}:{user_password}"])
    envs = []
    if proxy:
        envs.extend(["--env", f"http_proxy={proxy}", "--env", f"https_proxy={proxy}"])
    if gemini_mode:
        envs.extend(["-e", "SKIP_MODEL_CONTEXT=true"])
    if allow_network:
        envs.extend(["--env", "ALLOW_NETWORK=1"])
    envs.extend(['-e', 'PERSIST_DIR=/app/user_sessions'])
    gpus = ["--gpus", "all"] if enable_gpu else []
    ports = []
    if front_ui == "streamlit":
        ports.extend(["-p", f"{port}:8501"])
    safetly_args = '--security-opt=no-new-privileges'
    cmd_args = []
    if front_ui != "CLI":
        cmd_args.append(front_ui)
        
    output_queue.put(("STATUS", 1, "SUCCESS", "Configurations Prepared"))
    output_queue.put(("STATUS", 2, "RUNNING", "Starting Docker Container..."))

    command = docker_prefix + ["run", "-d", "--rm", "--name", container_name] + ports + [safetly_args] + gpus + mounts + envs + [CONTAINER_IMAGE] + cmd_args
    sys.stderr.write(" ".join(command) + "\n")
    try:
        subprocess.check_call(command)
        time.sleep(3)
        command = docker_prefix + ["ps", '-a', '|', 'grep', '-q', container_name]
        subprocess.check_call(command)
        output_queue.put(("STATUS", 2, "SUCCESS", "Container Started Successfully"))
        output_queue.put("Container started successfully.")
    except Exception as e:
        output_queue.put(("STATUS", 2, "ERROR", "Failed to Start Container"))
        output_queue.put(f"Error starting container: {e}, \n Command line: {' '.join(command)}")
        output_queue.put("DONE")
        return
        
    output_queue.put(("STATUS", 3, "RUNNING", "Waiting for Services Initialization... (~ 10 - 30 minutes for first launcher)"))
    log_command = docker_prefix + ["logs", "-f", container_name]
    log_process = subprocess.Popen(log_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)
    success = False
    start_time = time.time()
    timeout = 1600
    while (time.time() - start_time) < timeout:
        line = log_process.stdout.readline()
        if line:
            output_queue.put(line.strip())
            if "URL" in line:
                success = True
                break
        time.sleep(0.1)
        
    log_process.terminate()
    log_process.wait()
    
    if success:
        output_queue.put(("STATUS", 3, "SUCCESS", "Services Initialized & Ready"))
    else:
        output_queue.put(("STATUS", 3, "ERROR", "Initialization Failed or Timeout"))
        err = log_process.stderr.read()
        if err:
            output_queue.put(f"Log error: {err}")
            
    output_queue.put("DONE")
    output_queue.put(f"SUCCESS:{success}")

def get_child_pids(pid):
    try:
        output = subprocess.check_output(
            ['wmic', 'process', 'where', f"(ParentProcessId={pid})", 'get', 'ProcessId'],
            stderr=subprocess.STDOUT
        ).decode('utf-8', errors='ignore').strip()
        if not output: return []
        lines = output.split('\n')
        if lines and lines[0].strip() == 'ProcessId': lines = lines[1:]
        return [int(line.strip()) for line in lines if line.strip().isdigit()]
    except Exception as e:
        sys.stderr.write(f"Error getting child PIDs for {pid}: {e}\n")
        return []

def get_all_descendants(pid, include_self=False):
    descendants = [pid] if include_self else []
    children = get_child_pids(pid)
    for child in children:
        descendants.append(child)
        descendants += get_all_descendants(child)
    return descendants

def is_port_occupied(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def get_pid_using_port(port):
    for conn in psutil.net_connections():
        if conn.laddr.port == port and conn.status == 'LISTEN':
            return conn.pid
    return None

def start_bypass(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, enable_gpu, output_queue, user_name="admin", user_password="admin", gemini_mode=False, port=8501, allow_network=False):
    import copy
    if front_ui != "streamlit":
        output_queue.put("Error: In Bypass mode, only streamlit is supported. Chainlit and CLI modes are disabled.")
        output_queue.put("DONE")
        return
        
    output_queue.put(("STATUS", 1, "RUNNING", "Preparing Bypass Environment..."))
    env = copy.deepcopy(os.environ)
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    if gemini_mode:
        env["SKIP_MODEL_CONTEXT"] = "true"
    if user_name and user_password:
        env["APP_USER"] = f"{user_name}:{user_password}" 
    if conda_meta: env["CONDA_META_DATABASE"] = conda_meta
    if workflow: env["WORKFLOW_DATABASE"] = workflow
    if user_ext: env["USER_EXT_DATABASE"] = user_ext
    if cache: env["WORK_DIR"] = cache
    if port: env["BIOAG_PORT"] = str(port)
        
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env["PYTHONPATH"] = os.path.join(script_dir, 'bioag')
    env["BIOGEN_BYPASSMODE"] = "true"
    env["TQDM_DISABLE"] = "1"
    env["COOKIE_PASSWORD"] = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    if os.path.exists(os.path.join(cache, 'user_sessions'+st.session_state.random_key, f"{user_name}.json")):
        print(f"Removing existing user session file for {user_name}\n")
        os.remove(os.path.join(cache, 'user_sessions'+st.session_state.random_key, f"{user_name}.json"))
    else: 
        print(f"No existing user session file for {user_name}\n")
        
    if not st.session_state.get('random_id', None):
        random_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        st.session_state.random_id = random_id
    config_base = os.path.join(script_dir, 'config')
    os.makedirs(config_base, exist_ok=True)
        
    target_config_dir = os.path.join(config_base, f"bioag_temp_{st.session_state.random_id}")
    source_config_dir = os.path.join(script_dir, 'bioag', 'bioGen', 'config')
    
    if os.path.exists(target_config_dir):
        shutil.rmtree(target_config_dir)
    shutil.copytree(source_config_dir, target_config_dir)
    
    if configure:
        sys.stderr.write(f"Using user-provided config: {configure} to {target_config_dir}/system_config.yaml\n")
        os.environ['SYSTEM_CONFIG_PATH'] = target_config_dir
        env['SYSTEM_CONFIG_PATH'] = target_config_dir
        shutil.copy(configure, os.path.join(target_config_dir, 'system_config.yaml'))

    streamlit_path = os.path.join(script_dir, 'bioag', 'bioGen', 'web', 'app_streamlit1.py')
    cmd = [micromamba_path, 'run', '-p', biogen_env, 'streamlit', 'run', '--server.headless=true', streamlit_path, '--server.port', str(port)]
    if not allow_network:
        cmd = cmd + ['--server.address=127.0.0.1']
    sys.stderr.write("Command to execute: " + " ".join(cmd) + "\n")
    
    log_file_path = None
    if cache:
        log_dir = os.path.join(cache, 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{user_name}_bioag_{st.session_state.random_id}.log")
        
    init_complete = threading.Event()

    def read_pipe(pipe, queue, is_stderr, pid, event, log_file_path=None):
        reported = False
        try: 
            for line in iter(pipe.readline, ''):
                if line:
                    sys.stderr.write(f"[PID {pid}] {'[ERR]' if is_stderr else '[OUT]'} {line}")
                    stripped = line.strip()
                    queue.put(("ERR: " if is_stderr else "") + stripped)
                    if not reported and "http" in stripped.lower():
                        event.set()
                        reported = True
                    if log_file_path:
                        with open(log_file_path, 'a') as f:
                            f.write(f"{line}")
        except Exception as e:
            sys.stderr.write(f"Error reading pipe for PID {pid}: {e}\n")
        pipe.close()
        sys.stderr.write(f"Output reader thread for PID {pid} finished.\n")

    output_queue.put(("STATUS", 1, "SUCCESS", "Environment Prepared"))
    output_queue.put(("STATUS", 2, "RUNNING", "Launching Subprocess..."))

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True, env=env, cwd=script_dir)
        pid = process.pid
        st.session_state.bypass_process = process
        st.session_state.bypass_config_dir = target_config_dir
        
        sys.stderr.write(f"Bypass process started with PID {pid}\n")
        output_queue.put("Process starting up...")
        output_queue.put(("STATUS", 2, "SUCCESS", f"Subprocess Launched (PID: {pid})"))
        output_queue.put(("STATUS", 3, "RUNNING", "Waiting for Network Initialization..."))

        stdout_thread = threading.Thread(target=read_pipe, args=(process.stdout, output_queue, False, pid, init_complete, log_file_path))
        stderr_thread = threading.Thread(target=read_pipe, args=(process.stderr, output_queue, True, pid, init_complete, log_file_path))
        add_script_run_ctx(stdout_thread)
        add_script_run_ctx(stderr_thread)
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        sys.stderr.write("Waiting for 'http' initialization signal...\n")
        
        startup_timeout = 120 
        if not init_complete.wait(timeout=startup_timeout):
            if process.poll() is not None:
                exit_code = process.returncode
                output_queue.put(("STATUS", 3, "ERROR", f"Process Terminated (Exit: {exit_code})"))
                output_queue.put(f"Error: Process (PID {pid}) terminated unexpectedly during startup. Exit code: {exit_code}")
            else:
                output_queue.put(("STATUS", 3, "ERROR", f"Initialization timeout reached for PID {pid}."))
                output_queue.put(f"Error: Initialization timeout (s) reached for PID {pid}.")
            if 'bypass_config_dir' in st.session_state:
                shutil.rmtree(st.session_state.bypass_config_dir)
                del st.session_state.bypass_config_dir
            output_queue.put(f"SUCCESS:False")
            output_queue.put("DONE")
            return

        sys.stderr.write(f"Initialization signal received for PID {pid}.\n")
        descendants = get_all_descendants(pid)
        actual_pid = None
        find_start = time.time()
        find_timeout = 10 
        while time.time() - find_start < find_timeout:
            try:
                cmd_net = f'netstat -ano | findstr :{port}'
                output = subprocess.check_output(cmd_net, shell=True).decode('utf-8', errors='ignore')
                for line in output.splitlines():
                    if 'LISTENING' in line:
                        parts = re.split(r'\s+', line.strip())
                        if parts and parts[-1].isdigit():
                            listen_pid = int(parts[-1])
                            if listen_pid in descendants:
                                task_cmd = f'tasklist /fi "PID eq {listen_pid}"'
                                task_output = subprocess.check_output(task_cmd, shell=True).decode('utf-8', errors='ignore')
                                if 'python.exe' in task_output.lower():
                                    actual_pid = listen_pid
                                    break
                if actual_pid: break
            except Exception as e:
                sys.stderr.write(f"Error in finding listening PID: {e}\n")
            time.sleep(1)

        if actual_pid:
            output_queue.put(f"Initialization:{actual_pid}")
            sys.stderr.write(f"Found listening Python PID: {actual_pid}\n")
        else:
            output_queue.put(f"Initialization:{pid}")
            output_queue.put("Warning: Could not find the Python PID listening on the port. Using parent PID instead.")
            sys.stderr.write("Could not find listening Python PID. Using parent PID.\n")
            
        sys.stderr.write(f"Initialization confirmed for PID {actual_pid or pid}. Returning, process runs in background.\n")
        output_queue.put(("STATUS", 3, "SUCCESS", "Local Server is Active"))
        output_queue.put(f"SUCCESS:True")
        output_queue.put("DONE")
        time.sleep(9) 
        return 

    except Exception as e:
        sys.stderr.write(f"Error starting process: {pid}\nCommand line: {' '.join(cmd)}\n")
        output_queue.put(("STATUS", 2, "ERROR", "Process Launch Failed"))
        output_queue.put(f"Error starting process: {pid}")
        if 'bypass_config_dir' in st.session_state:
            shutil.rmtree(st.session_state.bypass_config_dir)
            del st.session_state.bypass_config_dir
        output_queue.put(f"SUCCESS:False")
        output_queue.put("DONE")
        return

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
            subprocess.check_call(docker_prefix + ["rm", container_name])
            output_queue.put(("STATUS", 3, "SUCCESS", "Container Removed Successfully"))
            output_queue.put(f"Stopped and removed container {container_name}")
        else:
            output_queue.put(("STATUS", 1, "SKIPPED", "No Running Container Found"))
            output_queue.put(("STATUS", 2, "SKIPPED", "Stop Skipped"))
            output_queue.put(("STATUS", 3, "SKIPPED", "Remove Skipped"))
    except Exception as e:
        output_queue.put(("STATUS", 1, "ERROR", "Error During Termination"))
        output_queue.put(f"Error stopping container: {e}")
    output_queue.put("DONE")

def stop_bypass_task(output_queue):
    output_queue.put(("STATUS", 1, "RUNNING", "Locating Bypass Process..."))
    if 'bypass_process' in st.session_state and st.session_state.bypass_process:
        process = st.session_state.bypass_process
        output_queue.put(("STATUS", 1, "SUCCESS", f"Process Found (PID {process.pid})"))

        output_queue.put(("STATUS", 2, "RUNNING", "Terminating Process..."))
        process.terminate()
        process.wait()
        output_queue.put(("STATUS", 2, "SUCCESS", "Process Terminated"))

        output_queue.put(("STATUS", 3, "RUNNING", "Cleaning Up Configurations..."))
        if 'bypass_config_dir' in st.session_state and os.path.exists(st.session_state.bypass_config_dir):
            shutil.rmtree(st.session_state.bypass_config_dir)
            del st.session_state.bypass_config_dir
        del st.session_state.bypass_process
        output_queue.put(("STATUS", 3, "SUCCESS", "Cleanup Complete"))
        output_queue.put("Stopped bypass process and cleaned up config.")
    else:
        output_queue.put(("STATUS", 1, "SKIPPED", "No Running Process Found"))
        output_queue.put(("STATUS", 2, "SKIPPED", "Termination Skipped"))
        output_queue.put(("STATUS", 3, "SKIPPED", "Cleanup Skipped"))
        output_queue.put("No running bypass process.")
    output_queue.put("DONE")

def render_config_form(config, prefix=""):
    for key, value in config.items():
        full_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            st.subheader(key.capitalize())
            render_config_form(value, prefix=full_key)
        elif isinstance(value, bool):
            st.checkbox(key.capitalize(), value=value, key=full_key)
        elif isinstance(value, (int, float)):
            st.number_input(key.capitalize(), value=value, key=full_key)
        elif isinstance(value, str):
            input_type = "password" if "api_key" in key.lower() else "default"
            st.text_input(key.capitalize(), value=value, key=full_key, type=input_type)
        else:
            st.text_input(key.capitalize(), value=str(value), key=full_key)

def collect_edited_config(config, prefix=""):
    edited = {}
    for key, value in config.items():
        full_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            edited[key] = collect_edited_config(value, prefix=full_key)
        else:
            edited[key] = st.session_state.get(full_key, value)
    return edited

def cleanup_bypass():
    if 'bypass_process' in st.session_state and st.session_state.bypass_process:
        st.session_state.bypass_process.terminate()
        st.session_state.bypass_process.wait()
    if 'bypass_config_dir' in st.session_state and os.path.exists(st.session_state.bypass_config_dir):
        shutil.rmtree(st.session_state.bypass_config_dir)
atexit.register(cleanup_bypass)

def _xor_decrypt(b64_str: str, key: str) -> str:
    if not key:
        raise ValueError("decrypt_key cannot be empty")
    encrypted = base64.b64decode(b64_str)
    key_bytes = key.encode("utf-8")
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")

DEBUG = False or os.getenv("BIOLAUNCHER_DEBUG", "False").lower() in ("true", "1", "yes") or os.path.exists("DEBUG.txt")
st.session_state.DEBUG = DEBUG
def write_to_debug_file(message: str, DEBUG: bool = st.session_state.DEBUG):
    if not DEBUG:
        return
    if not hasattr(write_to_debug_file, "debug_f"):
        write_to_debug_file.debug_f = open("debug.log", "w", encoding="utf-8")
        # write time
        write_to_debug_file.debug_f.write(f"Debug log started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        ## write system info
        write_to_debug_file.debug_f.write(f"System: {platform.system()} {platform.release()} {platform.version()}\n")
        write_to_debug_file.debug_f.write(f"Python version: {platform.python_version()}\n")
        write_to_debug_file.debug_f.write(f"Streamlit version: {st.__version__}\n")
        write_to_debug_file.debug_f.write(f"Streamlit session state: {st.session_state}\n")
        write_to_debug_file.debug_f.write(f"Streamlit config: {st.config}\n")
        write_to_debug_file.debug_f.write(f"Streamlit command line: {' '.join(sys.argv)}\n")
        # writ system path
        write_to_debug_file.debug_f.write(f"System path: {sys.path}\n")
        write_to_debug_file.debug_f.write(f"=========DEBUG=========\n")
    # if AccessKeyId=*** in message, replace it with asterisks
    if "AccessKeyId=" in message:
        message = re.sub(r"AccessKeyId=.*", "AccessKeyId=***", message)
    write_to_debug_file.debug_f.write(message + "\n")
    write_to_debug_file.debug_f.flush()

def parse_bio_config(json_source: str, total_version: str, decrypt_key: str, max_size: int = 2_097_152) -> dict:
    write_to_debug_file("Featch config file...\n")
    if json_source.startswith(("https://")):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(
                json_source, 
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            )
            with urlopen(req, timeout=15, context=ssl_context) as resp:
                # Prevent oversized responses
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    raise ValueError("JSON response too large")
                raw = resp.read(max_size + 1)
                if len(raw) > max_size:
                    raise ValueError("JSON response too large")
                config = json.loads(raw.decode("utf-8"))
                write_to_debug_file(f"Config file fetched from {json_source}, size: {len(raw)} bytes")
        except URLError as e:
            raise ValueError(f"Failed to fetch URL: {e}") from e
    else:
        if not os.path.isfile(json_source):
            raise FileNotFoundError(f"JSON file not found: {json_source}")
        file_size = os.path.getsize(json_source)
        if file_size > max_size:
            raise ValueError("JSON file too large")
        with open(json_source, "r", encoding="utf-8") as f:
            config = json.load(f)

    if total_version not in config:
        raise ValueError(f"Total version '{total_version}' not found")
    ver = config[total_version]

    ag = ver["BioAG"]
    bioag = {
        "version": ag["version"],
        "update_url": _xor_decrypt(ag["update_url"], decrypt_key),
        "update_url2": _xor_decrypt(ag["update_url2"], decrypt_key),
        "tag": _xor_decrypt(ag["tag"], decrypt_key),
    }

    bw = ver["BioWorker"]
    bioworker = {
        "version": bw["version"],
        "update_url": _xor_decrypt(bw["update_url"], decrypt_key),
        "update_url2": _xor_decrypt(bw["update_url2"], decrypt_key),
        "tag": _xor_decrypt(bw["tag"], decrypt_key),
    }

    write_to_debug_file(f"BioAG version: {bioag['version']}, tag: {bioag['tag']}")
    ## write all json to debug file
    write_to_debug_file(f"{bioag}\n{bioworker}\n")

    return {"BioAG": bioag, "BioWorker": bioworker}

def main():
    st.set_page_config(page_title="BioGAIP Container Launcher", page_icon="🚀", layout="wide")
    st.title("🚀 BioGAIP Container Launcher")
    st.markdown("A user-friendly tool to launch and manage BioAG and bioworker containers.")
    
    if 'license_accepted' not in st.session_state:
        st.session_state.license_accepted = False
    if not st.session_state.license_accepted:
        st.warning("📜 AGPL-3 License Agreement")
        st.markdown("""
        **AGPL-3.0 License**
        BioGAIP, bioAG, and bioWorker are licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
        
        Copyright (C) 2025 BioGAIP Team.

        This program is free software: you can redistribute it and/or modify
        it under the terms of the GNU Affero General Public License as
        published by the Free Software Foundation, either version 3 of the
        License, or (at your option) any later version.

        This program is distributed in the hope that it will be useful,
        but WITHOUT ANY WARRANTY; without even the implied warranty of
        MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
        GNU Affero General Public License for more details.

        You should have received a copy of the GNU Affero General Public License
        along with this program. If not, see <http://www.gnu.org/licenses/>.
        
        **Important Disclaimer**
        
        **THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
        AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
        LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
        OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
        SOFTWARE.**
        """)
        agree = st.checkbox("I accept the terms of the AGPL-3.0 License and understand there is no warranty or liability.")
        if st.button("Continue") and agree:
            st.session_state.license_accepted = True
            st.rerun()
        st.stop()
        
    if 'step' not in st.session_state:
        st.session_state.step = 1
        st.session_state.params = {}
        st.session_state.configure_path = None
        st.session_state.config_method = None
        
    if st.session_state.get('random_key', None) is None:
        st.session_state.random_key = '_' + random.randbytes(3).hex()
        
    if 'docker_prefix' not in st.session_state:
        st.session_state.docker_prefix = None
    if 'docker_runtime' not in st.session_state:
        st.session_state.docker_runtime = None
        
    if 'bypass_mode' not in st.session_state: st.session_state.bypass_mode = False
    if 'use_tsinghua_mirror' not in st.session_state: st.session_state.use_tsinghua_mirror = False
    if 'force_mode' not in st.session_state: st.session_state.force_mode = False
    if 'allow_network_visit' not in st.session_state: st.session_state.allow_network_visit = False
    if 'skip_bioagversion_check' not in st.session_state: st.session_state.skip_bioagversion_check = False

    if st.session_state.step == 1:
        st.header("Step 1: Configuration Check")
        with st.expander("Details", expanded=True):
            if not st.session_state.bypass_mode:
                st.write("Checking for Docker installation...")
                native_docker = check_native_docker()
                wsl_docker = check_wsl_docker()
                wsl_ubuntu = check_wsl_ubuntu()
                st.session_state.needs_docker_install = False
                
                if native_docker:
                    st.success("✅ Docker is installed natively.")
                    st.session_state.docker_prefix = ["docker"]
                    st.session_state.docker_runtime = 'native'
                elif wsl_docker:
                    st.success("✅ Docker is installed in WSL2.")
                    try:
                        _ = subprocess.run(['wsl', '-u', 'root', 'service', 'docker', 'start'])
                    except Exception as e:
                        st.error(f"❌ Failed to start Docker service in WSL2: {e}")
                    st.session_state.docker_prefix = ["wsl", "docker"]
                    st.session_state.docker_runtime = 'wsl'
                else:
                    st.error("❌ Docker is not installed natively or in WSL2.")
                    if wsl_ubuntu:
                        st.info("✅ WSL2 Ubuntu detected. We can automatically install Docker for you in the next step.")
                        st.session_state.needs_docker_install = True
                        st.session_state.docker_prefix = ["wsl", "docker"]
                        st.session_state.docker_runtime = 'wsl'
                    else:
                        st.markdown("""
                        Need help? Follow these guides:
                        - [Install Docker Desktop on Windows](https://docs.docker.com/desktop/install/windows-install/)
                        - [Install WSL2 and Docker](https://docs.docker.com/desktop/wsl/install/)
                        - [Install docker in WSL2](https://gist.github.com/dehsilvadeveloper/c3bdf0f4cdcc5c177e2fe9be671820c7)
                        - Try Bypass mode in advanced setting
                        """)
            else:
                st.write("Checking for Micromamba and BioGAIP environment...")
                if os.path.exists(micromamba_path) and os.path.exists(installed_flag):
                    st.success("✅ Micromamba and BioGAIP environment are ready.")
                else:
                    st.warning("❌ Micromamba or BioGAIP environment not found. Please install.")
                    if st.button("Install Micromamba and Environment"):
                        @st.dialog("Installing Micromamba and Environment")
                        def install_micromamba():
                            inject_dialog_style()
                            st.markdown("This may take a while depending on internet speed.")
                            output_queue = queue.Queue()
                            def install_thread():
                                try:
                                    url = "https://micro.mamba.pm/api/micromamba/win-64/latest"
                                    output_queue.put("Downloading micromamba...")
                                    response = requests.get(url, stream=True)
                                    total_size = int(response.headers.get('content-length', 0))
                                    tar_bz2_path = os.path.join(script_dir, 'micromamba.tar.bz2')
                                    with open(tar_bz2_path, 'wb') as f:
                                        downloaded = 0
                                        last_downloaded = 0
                                        for data in response.iter_content(1024):
                                            downloaded += len(data)
                                            f.write(data)
                                            if (downloaded - last_downloaded)/total_size > 0.1: 
                                                output_queue.put(f"Download progress: {downloaded / total_size * 100:.2f}%")
                                                last_downloaded = downloaded
                                    output_queue.put("Download complete.")
                                    output_queue.put("Extracting...")
                                    with tarfile.open(tar_bz2_path, 'r:bz2') as tar:
                                        tar.extractall(script_dir)
                                    output_queue.put("Extraction complete.")
                                    lib_bin_mm = os.path.join(script_dir, 'Library', 'bin', 'micromamba.exe')
                                    shutil.move(lib_bin_mm, micromamba_path)
                                    output_queue.put("Moved micromamba.exe")
                                    os.remove(tar_bz2_path)
                                    shutil.rmtree(os.path.join(script_dir, 'Library'))
                                    if not os.path.exists(envs_dir): os.makedirs(envs_dir)
                                    output_queue.put("Creating bioGAIP environment...")
                                    if not os.path.exists(env_yaml):
                                        output_queue.put(f"ERR: env.yaml not found at ")
                                        output_queue.put("DONE")
                                        return
                                    if 'use_tsinghua_mirror' in st.session_state and st.session_state.use_tsinghua_mirror:
                                        subprocess.check_call([micromamba_path, 'config', 'append', 'channels', 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main'])
                                        subprocess.check_call([micromamba_path, 'config', 'append', 'channels', 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free'])
                                        subprocess.check_call([micromamba_path, 'config', 'append', 'channels', 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge'])
                                        subprocess.check_call([micromamba_path, 'config', 'set', 'channel_priority', 'strict'])
                                        output_queue.put("Using Tsinghua mirror for channels.")
                                    create_cmd = [micromamba_path, 'create', '-p', biogen_env, '-f', env_yaml, '-y']
                                    process = subprocess.Popen(create_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                                    for line in iter(process.stdout.readline, ''): output_queue.put(line.strip())
                                    for line in iter(process.stderr.readline, ''): output_queue.put(f"ERR: {line.strip()}")
                                    process.wait()
                                    if process.returncode == 0:
                                        output_queue.put("Environment created successfully.")
                                        with open(installed_flag, "w") as f: f.write("")
                                    else:
                                        output_queue.put(f"Error creating environment: return code {process.returncode}")
                                    install_cmd = [micromamba_path, 'run', '-p', biogen_env, 'pip', 'install', '-e', os.path.join(script_dir, 'bioag')]
                                    output_queue.put("DONE")
                                except Exception as e:
                                    st.session_state.bypass_init=False
                                    output_queue.put(f"Error: {e}")
                                    output_queue.put("DONE")
                                    
                            thread = threading.Thread(target=install_thread)
                            add_script_run_ctx(thread)
                            thread.start()
                            
                            progress_bar = st.progress(0)
                            output_text = ""
                            output_container = st.empty()
                            start_time = time.time()
                            timeout = 1800 
                            
                            while True:
                                if time.time() - start_time > timeout: break
                                try:
                                    line = output_queue.get(timeout=0.1)
                                    if line == "DONE": break
                                    output_text += line + "\n"
                                    output_container.text_area("Installation Logs", output_text, height=300)
                                    if "Download progress:" in line:
                                        percent_str = line.split(":")[1].strip().rstrip("%")
                                        progress_bar.progress(float(percent_str) / 100 * 0.5)
                                    if "Download complete." in line: progress_bar.progress(0.5)
                                    if "Extraction complete." in line: progress_bar.progress(0.75)
                                    if "Environment created successfully." in line: progress_bar.progress(1.0)
                                except queue.Empty: pass
                                
                            thread.join()
                            
                            if os.path.exists(micromamba_path) and os.path.exists(installed_flag):
                                st.success("Installation complete. Please close this dialog using the top-right 'X', recheck Bypass mode, and click Next to continue.")
                            else:
                                st.error("Installation failed. Please close this dialog and try again.")
                                st.session_state.bypass_init=False
                                
                        st.session_state.bypass_init=True
                        install_micromamba()

        next_disabled = True
        if not st.session_state.bypass_mode:
            if st.session_state.docker_prefix and not st.session_state.get('needs_docker_install', False):
                running_containers = get_running_bioag_containers(st.session_state.docker_prefix)
                if running_containers:
                    st.warning(f"⚠️ The following bioag containers are already running: {', '.join(running_containers)}")
                    if st.session_state.get('force_mode', False):
                        st.info("Force mode enabled. You can proceed, but ensure ports do not conflict.")
                        next_disabled = False
                    else:
                        st.info("Please stop the running containers before proceeding.")
                        next_disabled = True
                    col1, col2 = st.columns(2)
                    if col1.button("🛑 Stop Running Containers"):
                        @st.dialog("Confirm Termination")
                        def confirm_terminate():
                            inject_dialog_style()
                            st.warning("Terminating these containers may cause data loss or interrupt ongoing processes. Are you sure?")
                            st.write("Containers to terminate:")
                            for c in running_containers: st.write(f"- {c}")
                            col_confirm1, col_confirm2 = st.columns(2)
                            if col_confirm1.button("Yes, Terminate"):
                                docker_prefix = st.session_state.docker_prefix
                                for c in running_containers:
                                    try:
                                        subprocess.check_call(docker_prefix + ["stop", c])
                                        subprocess.check_call(docker_prefix + ["rm", c])
                                        st.success(f"Stopped and removed {c}")
                                    except Exception as e:
                                        st.error(f"Error stopping {c}: {e}")
                                st.success("Termination complete. The page will now refresh.")
                                time.sleep(1)
                                st.rerun()
                            if col_confirm2.button("No"):
                                st.rerun()
                        confirm_terminate()
                else:
                    next_disabled = False
            elif st.session_state.get('needs_docker_install', False):
                next_disabled = False
            else:
                next_disabled = True
        else:
            if os.path.exists(micromamba_path) and os.path.exists(installed_flag): next_disabled = False
            else: next_disabled = True

        with st.expander("Advanced Options", expanded=st.session_state.bypass_mode):
            bypass_mode = st.checkbox("Use Bypass Mode (lightweight, no WSL2/Docker required, Windows only and experimental)", value=st.session_state.bypass_mode)
            if bypass_mode:
                st.error("WARNING: Bypass mode is highly experimental, unstable, and may cause unexpected errors or data loss. Use at your own risk!")
            use_tsinghua_mirror = st.checkbox("Use (Tsinghua) Mirror for Conda", value=st.session_state.use_tsinghua_mirror)
            force_mode = st.checkbox("Force Mode (continue even if containers are running)", value=st.session_state.force_mode)
            st.session_state.use_tsinghua_mirror = use_tsinghua_mirror
            skip_bioagversion_check = st.checkbox("Dont Check local BioAG version", value=st.session_state.skip_bioagversion_check)
            st.session_state.skip_bioagversion_check = skip_bioagversion_check
            #DEBUG=st.checkbox("Debug Mode (Selecting this option may result in log files containing sensitive information.)", value=st.session_state.get('DEBUG', False))
            #st.session_state.DEBUG = DEBUG
            allow_network_visit=st.checkbox("Allow Connections From the Local Network", value=st.session_state.allow_network_visit)
            st.session_state.allow_network_visit = allow_network_visit
        if st.session_state.get('DEBUG', False):
            st.info("Debug mode is enabled. This may log sensitive information, use with caution.")

        if bypass_mode != st.session_state.bypass_mode:
            st.session_state.bypass_mode = bypass_mode
            st.rerun()
        if force_mode != st.session_state.force_mode:
            st.session_state.force_mode = force_mode
            if force_mode: next_disabled = False
            st.rerun()

        if st.button("Next ➡️", key="next1", disabled=next_disabled):
            if st.session_state.bypass_mode:
                st.session_state.step = 2
            else:
                image_exists = check_image_exists(st.session_state.docker_prefix) if st.session_state.docker_prefix else False
                ## check images version
                version_match = False
                try:
                    bioag_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
                    TARGET_BIOAGVARSION_VALUE = bioag_config['BioAG']['version']
                except Exception as e:
                    write_to_debug_file(f"Error parsing config: {e}")
                    TARGET_BIOAGVARSION_VALUE = TARGET_BIOAGVARSION
                try:
                    inspect_cmd = st.session_state.docker_prefix + [
                        "inspect",
                        #"--format={{range .Config.Env}}{{println .}}{{end}}",
                        CONTAINER_IMAGE
                    ]
                    env_output = subprocess.check_output(inspect_cmd, stderr=subprocess.STDOUT).decode('utf-8', errors='ignore')
                    version_match = TARGET_BIOAGVARSION_VALUE in env_output
                    sys.stderr.write(f"Image env output: {env_output}, version match is {version_match}\n")
                    #log_info(f"Local image version check: {'✅ MATCH' if version_match else '❌ MISMATCH'}")
                except Exception as e:
                    sys.stderr.write(f"Could not read image env (image may be corrupted): {e}, check cmd is {" ".join(inspect_cmd)}\n")
                    version_match = False
                if st.session_state.get('skip_bioagversion_check', False):
                    version_match = True
                if not st.session_state.get('needs_docker_install', False) and image_exists and version_match:
                    st.session_state.step = 2 
                else:
                    st.session_state.step = 'pre_config'
            st.rerun()

    elif st.session_state.step == 'pre_config':
        st.header("System Pre-Configure")
        st.info("This setup prepares your Docker environment and retrieves necessary images. Please complete this step to avoid long waiting times during execution.")
        
        if 'preconfig_done' not in st.session_state:
            st.session_state.preconfig_done = False
            
        if st.button("Start System Pre-Configure", disabled=st.session_state.preconfig_done):
            @st.dialog("System Pre-Configuration Progress")
            def preconfig_dialog():
                inject_dialog_style()
                st.markdown("""
                <div style='margin-bottom: 15px;'>
                  <h4 style='margin-bottom: 0px;'>Preparing Environment</h4>
                  <span style="color: #666; font-size: 0.9em;">Please wait, this may take a while depending on your network speed...</span>
                  <br><span style="color: #666; font-size: 0.9em;">This process occurs only during the initial installation or when the version is updated.</span>
                </div>
                """, unsafe_allow_html=True)
                
                output_queue = queue.Queue()
                docker_prefix = st.session_state.get('docker_prefix')
                docker_runtime = st.session_state.get('docker_runtime')
                needs_docker_install = st.session_state.get('needs_docker_install', False)
                
                steps_ui = {
                  1: st.empty(),
                  2: st.empty(),
                  3: st.empty()
                }

                render_step(steps_ui[1], "PENDING", "Docker Engine Setup")
                render_step(steps_ui[2], "PENDING", "User Permissions Configuration")
                render_step(steps_ui[3], "PENDING", "Docker Image Verification & Build")
                
                st.markdown("<br>", unsafe_allow_html=True)
                log_expander = st.expander("Detailed Process Logs")
                log_container = log_expander.empty()
                
                def task():
                    try:
                        # Step 1
                        if needs_docker_install:
                            output_queue.put(("STATUS", 1, "RUNNING", "Installing Docker Engine..."))
                            cmds = [
                                ["wsl", "-u", "root", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                                ["wsl", "-u", "root", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "docker.io"],
                                ["wsl", "-u", "root", "service", "docker", "start"]
                            ]
                            for cmd in cmds:
                                output_queue.put(f"Executing: {' '.join(cmd)}")
                                run_cmd_with_output(cmd, output_queue)
                            st.session_state.needs_docker_install = False
                            output_queue.put(("STATUS", 1, "SUCCESS", "Docker Engine Setup Complete"))
                        else:
                            output_queue.put(("STATUS", 1, "SUCCESS", "Docker Engine Already Installed"))
                            
                        output_queue.put(f"Docker runtime is {docker_runtime}")
                        
                        # Step 2
                        if docker_runtime == 'wsl':
                            output_queue.put(("STATUS", 2, "RUNNING", "Configuring Docker Permissions..."))
                            try:
                                groups = subprocess.check_output(["wsl", "groups"]).decode()
                                if "docker" not in groups:
                                    user = subprocess.check_output(["wsl", "whoami"]).decode().strip()
                                    run_cmd_with_output(["wsl", "-u", "root", "usermod", "-aG", "docker", user], output_queue)
                                    run_cmd_with_output(["wsl", "-u", "root", "service", "docker", "restart"], output_queue)
                                    output_queue.put(("STATUS", 2, "SUCCESS", "User Permissions Configured"))
                                else:
                                    output_queue.put(("STATUS", 2, "SUCCESS", "User Permissions Already Configured"))
                            except Exception as e:
                                output_queue.put(f"WARN: Error checking/adding docker group: {e}")
                                output_queue.put(("STATUS", 2, "ERROR", "Failed to Configure Permissions"))
                        else:
                            output_queue.put(("STATUS", 2, "SKIPPED", "Native Docker - No Permission Config Needed"))
                            
                        # Step 3
                        output_queue.put(("STATUS", 3, "RUNNING", "Verifying & Building Docker Image... (~20-30 minutes, will download about 5 GB data, speed depend on your internet speed, This process only apply at first launch or version update)"))
                        build_image_if_needed(docker_prefix, output_queue)
                        
                        if check_image_exists(docker_prefix):
                            output_queue.put(("STATUS", 3, "SUCCESS", "Docker Image Ready"))
                        else:
                            output_queue.put(("STATUS", 3, "ERROR", "Docker Image Missing or Failed"))
                            
                        output_queue.put("DONE")
                    except Exception as e:
                        output_queue.put(f"Pre-Configuration Error: {e}")
                        output_queue.put("DONE")

                t = threading.Thread(target=task)
                add_script_run_ctx(t)
                t.start()
                
                out_text = ""
                while True:
                    try:
                        line = output_queue.get(timeout=0.2)
                        if line == "DONE": 
                            break
                        
                        if isinstance(line, tuple) and line[0] == "STATUS":
                            _, step_id, state, text = line
                            render_step(steps_ui[step_id], state, text)
                        else:
                            out_text += str(line) + "\n"
                            log_container.text_area("Logs", out_text, height=250)
                    except queue.Empty:
                        if not t.is_alive(): 
                            break
                            
                t.join()
                st.success("🎉 Pre-Configuration finished successfully! You may close this dialog using the top-right 'X'.")
                st.session_state.preconfig_done = True

            preconfig_dialog()

        cols = st.columns(3)
        if cols[0].button("⬅️ Back to Step 1"):
            st.session_state.step = 1
            st.rerun()
            
        if cols[2].button("Next ➡️", disabled=not st.session_state.get('preconfig_done', False)):
            st.session_state.step = 2
            st.rerun()

    elif st.session_state.step == 2:
        st.header("Step 2: Parameter Configuration")
        if st.session_state.config_method is None:
            st.subheader("Choose Your LLM API Configuration Method")
            st.markdown("""
            We need your LLM API information. This is essential to interact with LLM services.
            You can use open-source products like DeepSeek, or commercial platforms such as OpenAI, Gemini, Grok, etc.
            """)
            col1, col2 = st.columns(2)
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('Need our built configuration template? Download it from https://notebook.biogaip.top/src/configure.yaml (Please copy the URL and open it in your browser).')
            with col1:
                st.markdown("### 📤 Upload File\n**Pros:**\n- Quick and straightforward\n- Allow custom configurations\n**Cons:**\n- Requires preparing the file\n- Less flexibility")
                if st.button("Upload File", key="select_upload"):
                    st.session_state.config_method = "Upload File"
                    st.rerun()
            with col2:
                st.markdown("### ✏️ Online Edit\n**Pros:**\n- Edit directly in browser\n- Easy quick adjustments\n**Cons:**\n- Take more time to fill\n- Risk of input errors")
                if st.button("Select Online Edit", key="select_online"):
                    st.session_state.config_method = "Online Edit"
                    st.rerun()
        else:
            with st.form(key="params_form"):
                if not st.session_state.bypass_mode:
                    front_ui = st.selectbox("Front UI", ["CLI", "streamlit"], index=1, help="Choose the frontend interface.")
                else:
                    front_ui = "streamlit"
                    st.write("Front UI: streamlit")
                    st.info("In Bypass mode, chainlit and CLI modes are disabled.")
                st.subheader(f"Configuration: {st.session_state.config_method}")
                if st.session_state.config_method == "Upload File":
                    uploaded_file = st.file_uploader("Configure File (required)", type=None, help="Upload your configuration file.")
                    if uploaded_file is not None:
                        with tempfile.NamedTemporaryFile(dir=cache_path, delete=False, suffix=f"_bioag{os.path.splitext(uploaded_file.name)[1]}") as tmp:
                            shutil.copyfileobj(uploaded_file, tmp)
                            st.session_state.configure_path = tmp.name
                        st.info(f"Uploaded: {uploaded_file.name}")
                else:
                    try: 
                        config_yaml = 'assets/system_config.yaml'
                        config = yaml.safe_load(open(config_yaml, 'r'))
                    except Exception as e:
                        config_yaml = 'resources/assets/system_config.yaml'
                        config = yaml.safe_load(open(config_yaml, 'r'))
                    st.subheader("Edit Model Clients")
                    for client_name, client in config['model_client'].items():
                        with st.expander(client_name, expanded=True):
                            render_config_form(client, prefix=client_name)
                            
                conda_meta = st.text_input("Conda Meta DB (optional)", value=st.session_state.params.get("conda_meta", ""), help="Path to Conda meta database directory.")
                workflow = st.text_input("Workflow DB (optional)", value=st.session_state.params.get("workflow", ""), help="Path to workflow database directory.")
                user_ext = st.text_input("User Ext DB (optional)", value=st.session_state.params.get("user_ext", ""), help="Path to user extension database directory.")
                
                home_dir = os.path.expanduser("~")
                st.session_state.cache_default = os.path.join(home_dir, "bioGen", "cache")
                if st.session_state.get('docker_prefix', None) is not None and st.session_state.docker_runtime == 'wsl' and st.session_state.get('bypass_mode', False) == False:
                    st.session_state.res_cache_default = "~/bioGen/res_cache"
                else:
                    st.session_state.res_cache_default = st.session_state.cache_default
                    
                if not os.path.exists(st.session_state.cache_default) and st.session_state.get('docker_prefix', None) != 'wsl':
                    os.makedirs(st.session_state.cache_default)
                elif st.session_state.get('docker_prefix', None) == 'wsl':
                    wsl_path = convert_to_docker_host_path(st.session_state.cache_default, st.session_state.docker_prefix)
                    subprocess.run(['wsl', '-u', '1000', 'mkdir', '-p', wsl_path])
                    
                if not os.path.exists(st.session_state.res_cache_default) and st.session_state.get('docker_prefix', None) != 'wsl':
                    os.makedirs(st.session_state.res_cache_default)
                elif st.session_state.get('docker_prefix', None) == 'wsl':
                    wsl_path = convert_to_docker_host_path(st.session_state.res_cache_default, st.session_state.docker_prefix)
                    subprocess.run(['wsl', '-u', '1000', 'mkdir', '-p', wsl_path])
                    
                cache = st.text_input("Cache Dir (optional)", value=st.session_state.params.get("cache", st.session_state.cache_default), help="Path to cache directory.")
                res_cache = st.text_input("Resource Cache Dir (optional)", value=st.session_state.params.get("res_cache", st.session_state.res_cache_default), help="Path to resource runtime, recommended to set it as WSL Internal Path to better performance.")
                
                if not st.session_state.bypass_mode and st.session_state.docker_runtime == 'wsl':
                    st.warning("⚠️ When using WSL Docker, ensure that all paths are accessible within WSL.\n Please read the Working across Windows and Linux file systems for details.")
                    st.warning("⚠️ For better performance, it's recommended to set cache and resource cache paths to WSL internal paths (e.g., ~/... ) instead of Windows paths (e.g., C:\\Users\\... ).")
                    
                proxy = st.text_input("HTTP Proxy (optional)", value=st.session_state.params.get("proxy", ""), help="HTTP proxy in format http://proxy:port")
                if not st.session_state.bypass_mode and st.session_state.docker_runtime == 'wsl':
                    st.warning("⚠️ When using WSL Docker, ensure that the proxy is accessible within WSL.")
                    
                user_name = st.text_input("User Name (optional)", value="admin", )
                user_password = st.text_input("Password (optional)", value="admin", type="password")
                st.info(f"Default user name and password are admin/admin, please change them in production environment!")
                
                #enable_gpu = st.checkbox("Enable GPU support", value=False, help="Enable NVIDIA GPU acceleration.") if not st.session_state.bypass_mode else False
                enable_gpu = False
                
                with st.expander("Advanced Options", expanded=False):
                    gemini_mode = st.checkbox("Activate Gemini Compatible Mode", value=False)
                    bioag_port = st.number_input("BioAG Frontend Port", min_value=1024, max_value=65535, value=8501, help="Port to expose the BioAG frontend UI.")
                    st.session_state.bioag_port = bioag_port
                    session_id = st.text_input('BioAG session id', value=st.session_state.get('random_key', '_' + f"{random.randbytes(3).hex()}"), help="BioAG session id.")
                    if session_id != st.session_state.random_key:
                        st.session_state.random_key = session_id
                        
                cols = st.columns(3)
                back_to_selection = cols[0].form_submit_button("⬅️ Back to Selection")
                back_to_step1 = cols[1].form_submit_button("⬅️ Back to Step 1")
                next_button = cols[2].form_submit_button("Next ➡️")
                
                if back_to_selection:
                    if st.session_state.configure_path:
                        os.unlink(st.session_state.configure_path)
                        st.session_state.configure_path = None
                    st.session_state.config_method = None
                    st.rerun()
                if back_to_step1:
                    if st.session_state.configure_path:
                        os.unlink(st.session_state.configure_path)
                        st.session_state.configure_path = None
                    st.session_state.step = 1
                    st.session_state.config_method = None
                    st.rerun()
                if next_button:
                    configure = None
                    if st.session_state.config_method == "Upload File":
                        if 'configure_path' not in st.session_state or not st.session_state.configure_path:
                            st.error("Configure file is required.")
                            st.stop()
                        else:
                            configure = st.session_state.configure_path
                    else:
                        edited_model_clients = {}
                        for client_name, client in config['model_client'].items():
                            edited_client = collect_edited_config(client, prefix=client_name)
                            edited_model_clients[client_name] = edited_client
                        config['model_client'] = edited_model_clients
                        with tempfile.NamedTemporaryFile(delete=False, suffix="_bioag.yaml") as tmp:
                            yaml.safe_dump(config, tmp, encoding='utf-8')
                            configure = tmp.name
                        st.session_state.configure_path = configure
                        
                    if configure:
                        st.session_state.params = {
                            "front_ui": front_ui, "configure": configure, "conda_meta": conda_meta,
                            "workflow": workflow, "user_ext": user_ext, "cache": cache, "proxy": proxy,
                            "user_name": user_name, "user_password": user_password, "enable_gpu": enable_gpu,
                            "gemini_mode": gemini_mode, 'bioag_port': bioag_port, 'random_key': st.session_state.random_key, 
                            'res_cache': res_cache, 'allow_network': st.session_state.allow_network_visit
                        }
                        st.session_state.step = 3
                        st.rerun()

    elif st.session_state.step == 3:
        st.header("Step 3: Execute")
        params = st.session_state.params
        docker_prefix = st.session_state.docker_prefix if 'docker_prefix' in st.session_state else None
        
        with st.expander("Parameters Summary", expanded=True):
            st.json(params)
            
        if st.session_state.bypass_mode:
            st.warning("⚠️ You are running in Bypass mode. All RAG System will Disabled to avoid a known issue. \nWe still recommend using the container mode")
        if not os.path.exists(os.path.join(st.session_state.cache_default, 'conda', '_PASS')):
            st.info("Environment not fully initialized yet. The first run may take longer (up to 10 min) to set up necessary resources. \n This process will only occur once if you dont change cache setting.")
        if st.session_state.get('random_key', None) is None:
            st.session_state.random_key = '_' + random.randbytes(3).hex()
        if not os.path.exists(os.path.join(st.session_state.cache_default, 'user_sessions' + st.session_state.random_key)):
            os.makedirs(os.path.join(st.session_state.cache_default, 'user_sessions' + st.session_state.random_key))
            
        # Determine Running State accurately via real-time logic
        run_disabled = False
        is_running = False
        running_containers = []
        
        if not st.session_state.bypass_mode:
            if docker_prefix:
                running_containers = get_running_bioag_containers(docker_prefix)
            if running_containers:
                is_running = True
                if not st.session_state.get('force_mode', False):
                    st.warning(f"⚠️ bioag instance is already running: {', '.join(running_containers)}. If you need start a new session, you need stop this first or enable Force Mode in Step 1.")
                    run_disabled = True
                else:
                    st.info(f"⚠️ bioag instance is running: {', '.join(running_containers)}. Force Mode is enabled, you can run another instance.")
        elif st.session_state.bypass_mode:
            if 'bypass_process' in st.session_state and st.session_state.bypass_process and st.session_state.bypass_process.poll() is None:
                st.warning("⚠️ Bypass process is already running. RUN button is disabled.")
                run_disabled = True
                is_running = True

        if is_running:
            port = params.get('bioag_port', 8501)
            if not st.session_state.get('force_mode', False): 
                container_name = "bioag" 
            else: 
                container_name = f"bioag_{port}"
            if container_name in get_running_bioag_containers(docker_prefix):
                st.success("✅ The environment is currently running!")
                st.markdown(f"**Application URL:** [http://127.0.0.1:{port}](http://127.0.0.1:{port})")

        cols = st.columns(3)
        if cols[0].button("⬅️ Back"):
            st.session_state.step = 2
            st.rerun()
            
        if cols[1].button("🛑 Stop Environment", disabled=not is_running):
            @st.dialog("Termination Progress")
            def stop_dialog():
                inject_dialog_style()
                st.markdown("<h4 style='margin-bottom: 0px;'>Stopping Resources</h4><span style='color: #666; font-size: 0.9em;'>Please wait while processes are safely terminated...</span>", unsafe_allow_html=True)
                s_ui = {1: st.empty(), 2: st.empty(), 3: st.empty()}
                render_step(s_ui[1], "PENDING", "Locating Resources")
                render_step(s_ui[2], "PENDING", "Terminating Processes")
                render_step(s_ui[3], "PENDING", "Cleaning Configurations")
                
                out_queue = queue.Queue()
                if not st.session_state.get('force_mode', False): 
                    container_name = "bioag" 
                else: 
                    container_name = f"bioag_{port}"
                #container_name = st.session_state.get('started_container_name', CONTAINER_NAME)
                
                def term_task():
                    if st.session_state.bypass_mode:
                        stop_bypass_task(out_queue)
                    else:
                        stop_container_task(docker_prefix, container_name, out_queue)

                tt = threading.Thread(target=term_task)
                add_script_run_ctx(tt)
                tt.start()
                
                log_expander = st.expander("Detailed Process Logs")
                log_container = log_expander.empty()
                out_text = ""
                
                while True:
                    try:
                        line = out_queue.get(timeout=0.2)
                        if line == "DONE": break
                        if isinstance(line, tuple) and line[0] == "STATUS":
                            render_step(s_ui[line[1]], line[2], line[3])
                        else:
                            out_text += str(line) + "\n"
                            log_container.text_area("Logs", out_text, height=250)
                    except queue.Empty:
                        if not tt.is_alive(): break
                tt.join()
                
                st.success("Termination process has finished successfully. You may close this dialog and continue.")
                if not st.session_state.bypass_mode and 'started_container_name' in st.session_state:
                    del st.session_state.started_container_name 
                if st.button("Close", use_container_width=True, type="primary"):
                    st.rerun()
            
            stop_dialog()

        if cols[2].button("▶️ Run", disabled=run_disabled):
            port = params['bioag_port']
            if st.session_state.bypass_mode and is_port_occupied(port):
                @st.dialog("Port Occupied")
                def handle_port_occupied():
                    inject_dialog_style()
                    pid = get_pid_using_port(port)
                    if pid:
                        st.write(f"Port {port} is occupied by process {pid}. Do you want to terminate it?")
                        col_y, col_n = st.columns(2)
                        if col_y.button("Yes, terminate it"):
                            try:
                                if os.name == 'nt': subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=True)
                                else: os.kill(pid, signal.SIGTERM)
                                time.sleep(2)
                                if not is_port_occupied(port):
                                    st.success("Process terminated successfully. Port is now free. Close this dialog using the top-right 'X' and click Run again.")
                                else:
                                    st.error("Failed to free the port after termination.")
                            except Exception as e:
                                st.error(f"Error terminating process: {e}")
                        if col_n.button("No, cancel"):
                            st.rerun()
                    else:
                        st.error("Unable to identify the process occupying the port. Please free the port manually.")
                handle_port_occupied()
                st.stop()
                
            @st.dialog("Execution Progress")
            def execution_dialog():
                inject_dialog_style()
                st.markdown("<h4 style='margin-bottom: 0px;'>Starting Environment</h4><span style='color: #666; font-size: 0.9em;'>Please wait while the environment launches...</span>", unsafe_allow_html=True)
                
                s_ui = {1: st.empty(), 2: st.empty(), 3: st.empty()}
                render_step(s_ui[1], "PENDING", "Preparing Configurations")
                render_step(s_ui[2], "PENDING", "Starting Engine")
                render_step(s_ui[3], "PENDING", "Waiting for Services Initialization (~ 10 - 30 minutes for first launch)")
                
                log_expander = st.expander("Detailed Process Logs")
                log_container = log_expander.empty()
                
                output_queue = queue.Queue()
                container_name = CONTAINER_NAME
                if st.session_state.get('force_mode', False):
                    container_name = f"bioag_{params['bioag_port']}"
                    
                def exec_task():
                    if not st.session_state.bypass_mode:
                        thread_docker_demo = threading.Thread(target=start_docker_demo, args=(docker_prefix, output_queue))
                        add_script_run_ctx(thread_docker_demo)
                        thread_docker_demo.start()
                        thread_docker_demo.join()
                        start_docker(
                            params["front_ui"], params["configure"], params["conda_meta"],
                            params["workflow"], params["user_ext"], params["cache"], params["proxy"],
                            params["enable_gpu"], docker_prefix, output_queue, params["user_name"], params["user_password"],
                            params["gemini_mode"], params['bioag_port'], container_name, params["res_cache"], params['random_key'], params['allow_network']
                        )
                    else:
                        start_bypass(
                            params["front_ui"], params["configure"], params["conda_meta"],
                            params["workflow"], params["user_ext"], params["cache"], params["proxy"],
                            params["enable_gpu"], output_queue, params["user_name"], params["user_password"],
                            params["gemini_mode"], params['bioag_port'], params['allow_network']
                        )

                te = threading.Thread(target=exec_task)
                add_script_run_ctx(te)
                te.start()
                
                out_text = ""
                final_success = False
                
                while True:
                    try:
                        line = output_queue.get(timeout=0.2)
                        if line == "DONE": break
                        if isinstance(line, tuple) and line[0] == "STATUS":
                            render_step(s_ui[line[1]], line[2], line[3])
                        elif isinstance(line, str):
                            if line.startswith("SUCCESS:") or line.startswith("Local URL:") or line.startswith("URL:") or line.startswith("URL:"):
                                final_success = True
                            elif line.startswith("Initialization:"):
                                try:
                                    st.session_state.bypass_mode_pid = int(line.split(":")[1])
                                except: pass
                            else:
                                out_text += str(line) + "\n"
                                log_container.text_area("Logs", out_text, height=250)
                    except queue.Empty:
                        if not te.is_alive(): break
                te.join()
                
                if final_success:
                    if not st.session_state.get('bypass_mode', False):
                        st.session_state.started_container_name = container_name
                    st.success(f"✅ Started container with front_ui={params['front_ui']}")
                    st.markdown(f"🎉 **Execution successful!** You can open your browser to [http://127.0.0.1:{params['bioag_port']}](http://127.0.0.1:{params['bioag_port']}) to continue with the next steps.")
                    if st.session_state.get('bypass_mode', False):
                        st.info("Note: In experimental Bypass mode, you may got a blank page at first open the url since the program needs to download and initialize some necessary resources, please wait for up to 5 minutes and then refresh the page. We are trying to optimize this process.")
                else:
                    st.error("❌ The container failed to start. Please check the output logs for details.")

                if st.button("Close", use_container_width=True, type="primary"):
                    st.rerun()
            
                st.info("You may now close this dialog, please bookmark the web url for reference.")

            execution_dialog()

if __name__ == "__main__":
    main()