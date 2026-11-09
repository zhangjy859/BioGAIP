import os
import sys
import time
import queue
import threading
import subprocess
import shutil
import tempfile
import requests
import tarfile
import random
import yaml
import signal
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from constants import (CONTAINER_IMAGE, CONTAINER_NAME, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 
                       CONFIG_JSON, cache_path, script_dir, micromamba_path, system, arch_name, 
                       envs_dir, biogen_env, env_yaml, installed_flag)
from ui import inject_dialog_style, render_step, render_config_form, collect_edited_config
from utils import is_port_occupied, get_pid_using_port, parse_bio_config, write_to_debug_file, run_cmd_with_output
from docker_mgr import (check_native_docker, check_wsl_docker, check_wsl_ubuntu, get_docker_prefix,
                        get_running_bioag_containers, check_image_exists, build_image_if_needed,
                        start_docker_demo, start_docker, stop_container_task)
from bypass_mgr import start_bypass, stop_bypass_task

def main():
    st.set_page_config(page_title="BioGAIP Container Launcher", page_icon="🚀", layout="wide")
    
    st.markdown("""
        <style>
        [data-testid="stHeader"] {display: none;}
        .stDeployButton {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

    st.title("🚀 BioGAIP Container Launcher")
    st.markdown("A user-friendly tool to launch and manage BioAG and bioworker containers.")
    
    if 'DEBUG' not in st.session_state:
        st.session_state.DEBUG = False or os.getenv("BIOLAUNCHER_DEBUG", "False").lower() in ("true", "1", "yes") or os.path.exists("DEBUG.txt")

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
        
    if 'docker_prefix' not in st.session_state: st.session_state.docker_prefix = None
    if 'docker_runtime' not in st.session_state: st.session_state.docker_runtime = None
        
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
                            st.markdown("This may take a while (up to 30 minutes) depending on internet speed.")
                            st.markdown("This process only occurs during the initial launch")
                            output_queue = queue.Queue()
                            def install_thread():
                                try:
                                    if system == "windows":
                                        url = "https://micro.mamba.pm/api/micromamba/win-64/latest"
                                    else:
                                        url = f"https://micro.mamba.pm/api/micromamba/{system}-{arch_name}/latest"
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
                                    if system == "windows":
                                        lib_bin_mm = os.path.join(script_dir, 'Library', 'bin', 'micromamba.exe')
                                    else:
                                        lib_bin_mm = os.path.join(script_dir, 'Library', 'bin', 'micromamba')
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
                                    process = subprocess.Popen(create_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
                                    for line in iter(process.stdout.readline, ''): output_queue.put(line.strip())
                                    for line in iter(process.stderr.readline, ''): output_queue.put(f"ERR: {line.strip()}")
                                    process.wait()
                                    if process.returncode == 0:
                                        output_queue.put("Environment created successfully.")
                                        with open(installed_flag, "w") as f: f.write("")
                                    else:
                                        output_queue.put(f"Error creating environment: return code {process.returncode}")
                                    subprocess.check_call([micromamba_path, 'run', '-p', biogen_env, 'pip', 'install', '-e', os.path.join(script_dir, 'bioag')])
                                    output_queue.put("DONE")
                                except Exception as e:
                                    st.session_state.bypass_init = False
                                    output_queue.put(f"Error: {e}")
                                    output_queue.put("DONE")
                                    
                            thread = threading.Thread(target=install_thread)
                            add_script_run_ctx(thread)
                            thread.start()
                            
                            progress_bar = st.progress(0)
                            output_text = ""
                            output_container = st.empty()
                            start_time = time.time()
                            
                            while True:
                                if time.time() - start_time > 1800: break
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
                                st.session_state.bypass_init = False
                                
                        st.session_state.bypass_init = True
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
                            if col_confirm2.button("No"): st.rerun()
                        confirm_terminate()
                else:
                    next_disabled = False
            elif st.session_state.get('needs_docker_install', False):
                next_disabled = False
        else:
            if os.path.exists(micromamba_path) and os.path.exists(installed_flag): next_disabled = False

        with st.expander("Advanced Options", expanded=st.session_state.bypass_mode):
            bypass_mode = st.checkbox("Use Bypass Mode (lightweight, no WSL2/Docker required, Windows only and experimental)", value=st.session_state.bypass_mode)
            if bypass_mode:
                st.error("WARNING: Bypass mode is highly experimental, unstable, and may cause unexpected errors or data loss. Use at your own risk!")
            use_tsinghua_mirror = st.checkbox("Use (Tsinghua) Mirror for Conda", value=st.session_state.use_tsinghua_mirror)
            force_mode = st.checkbox("Force Mode (continue even if containers are running)", value=st.session_state.force_mode)
            st.session_state.use_tsinghua_mirror = use_tsinghua_mirror
            skip_bioagversion_check = st.checkbox("Dont Check local BioAG version", value=st.session_state.skip_bioagversion_check)
            st.session_state.skip_bioagversion_check = skip_bioagversion_check
            allow_network_visit = st.checkbox("Allow Connections From the Local Network", value=st.session_state.allow_network_visit)
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
                version_match = False
                try:
                    with st.spinner("Check BioAG Update", show_time=True):
                        bioag_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
                        TARGET_BIOAGVARSION_VALUE = bioag_config['BioAG']['version']
                except Exception as e:
                    write_to_debug_file(f"Error parsing config: {e}")
                    TARGET_BIOAGVARSION_VALUE = TARGET_BIOAGVARSION
                try:
                    inspect_cmd = st.session_state.docker_prefix + ["inspect", CONTAINER_IMAGE]
                    env_output = subprocess.check_output(inspect_cmd, stderr=subprocess.STDOUT).decode('utf-8', errors='ignore')
                    version_match = TARGET_BIOAGVARSION_VALUE in env_output
                    sys.stderr.write(f"Image env output: {env_output}, version match is {version_match}\n")
                except Exception as e:
                    sys.stderr.write(f"Could not read image env: {e}\n")
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
                
                steps_ui = {1: st.empty(), 2: st.empty(), 3: st.empty()}
                render_step(steps_ui[1], "PENDING", "Docker Engine Setup")
                render_step(steps_ui[2], "PENDING", "User Permissions Configuration")
                render_step(steps_ui[3], "PENDING", "Docker Image Verification & Build")
                
                st.markdown("<br>", unsafe_allow_html=True)
                log_expander = st.expander("Detailed Process Logs")
                log_container = log_expander.empty()
                
                def task():
                    try:
                        if needs_docker_install:
                            output_queue.put(("STATUS", 1, "RUNNING", "Installing Docker Engine..."))
                            cmds = [
                                ["wsl", "-u", "root", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                                ["wsl", "-u", "root", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "docker.io"],
                                ["wsl", "-u", "root", "service", "docker", "start"]
                            ]
                            for cmd in cmds: run_cmd_with_output(cmd, output_queue)
                            st.session_state.needs_docker_install = False
                            output_queue.put(("STATUS", 1, "SUCCESS", "Docker Engine Setup Complete"))
                        else:
                            output_queue.put(("STATUS", 1, "SUCCESS", "Docker Engine Already Installed"))
                            
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
                        if line == "DONE": break
                        if isinstance(line, tuple) and line[0] == "STATUS":
                            render_step(steps_ui[line[1]], line[2], line[3])
                        else:
                            out_text += str(line) + "\n"
                            log_container.text_area("Logs", out_text, height=250)
                    except queue.Empty:
                        if not t.is_alive(): break
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
                user_ext = st.text_input("User Ext Resources (Directory with pdf, docx, txt, etc. Optional)", value=st.session_state.params.get("user_ext", ""), help="Path to user extension database directory.")
                
                home_dir = os.path.expanduser("~")
                st.session_state.cache_default = os.path.join(home_dir, "bioGen", "cache")
                if st.session_state.get('docker_prefix', None) is not None and st.session_state.docker_runtime == 'wsl' and st.session_state.get('bypass_mode', False) == False:
                    st.session_state.res_cache_default = "~/bioGen/res_cache"
                else:
                    st.session_state.res_cache_default = st.session_state.cache_default
                    
                if not os.path.exists(st.session_state.cache_default) and st.session_state.get('docker_prefix', None) != 'wsl':
                    os.makedirs(st.session_state.cache_default)
                elif st.session_state.get('docker_prefix', None) == 'wsl':
                    subprocess.run(['wsl', '-u', '1000', 'mkdir', '-p', f"/mnt/c/{st.session_state.cache_default.replace('C:\\', '').replace('\\', '/')}"]) 
                    
                if not os.path.exists(st.session_state.res_cache_default) and st.session_state.get('docker_prefix', None) != 'wsl':
                    os.makedirs(st.session_state.res_cache_default)
                
                cache = st.text_input("Cache Dir (optional)", value=st.session_state.params.get("cache", st.session_state.cache_default), help="Path to cache directory.")
                res_cache = st.text_input("Resource Cache Dir (optional)", value=st.session_state.params.get("res_cache", st.session_state.res_cache_default), help="Path to resource runtime, recommended to set it as WSL Internal Path to better performance.")
                
                if not st.session_state.bypass_mode and st.session_state.docker_runtime == 'wsl':
                    st.warning("⚠️ When using WSL Docker, ensure that all paths are accessible within WSL.\n Please read the Working across Windows and Linux file systems for details.")
                    st.warning("⚠️ For better performance, it's recommended to set cache and resource cache paths to WSL internal paths (e.g., ~/... ) instead of Windows paths (e.g., C:\\Users\\... ).")
                    
                proxy = st.text_input("HTTP Proxy (optional)", value=st.session_state.params.get("proxy", ""), help="HTTP proxy in format http://proxy:port")
                if not st.session_state.bypass_mode and st.session_state.docker_runtime == 'wsl':
                    st.warning("⚠️ When using WSL Docker, ensure that the proxy is accessible within WSL.")
                    
                user_name = st.text_input("User Name (optional)", value=st.session_state.get("user_name", "admin"), )
                user_password = st.text_input("Password (optional)", value=st.session_state.get("user_password", "admin"), type="password")
                remember_password = st.checkbox("Remember password", value=st.session_state.get("remember_password", False))
                st.session_state.remember_password = remember_password
                if remember_password:
                    st.session_state.user_name = user_name
                    st.session_state.user_password = user_password
                st.info(f"Default user name and password are admin/admin, please change them in production environment!")
                
                enable_gpu = False
                gemini_mode = False
                with st.expander("Advanced Options", expanded=False):
                    bioag_port = st.number_input("BioAG Frontend Port", min_value=1024, max_value=65535, value=st.session_state.get('bioag_port', 8501), help="Port to expose the BioAG frontend UI.")
                    st.session_state.bioag_port = bioag_port
                    local_storage = st.selectbox("Local Storage Method", ["File System (Json)", "SQLite"], index=1, help="Choose the local storage method for BioAG. File System is recommended for better performance and easier access to files.")
                    st.session_state.local_storage = local_storage
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
                        else: configure = st.session_state.configure_path
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
                            'res_cache': res_cache, 'allow_network': st.session_state.allow_network_visit, 'local_storage': local_storage
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
            
        run_disabled = False
        is_running = False
        running_containers = []
        
        if not st.session_state.bypass_mode:
            if docker_prefix: running_containers = get_running_bioag_containers(docker_prefix)
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
            container_name = f"bioag_{port}" if st.session_state.get('force_mode', False) else "bioag"
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
                container_name = f"bioag_{params['bioag_port']}" if st.session_state.get('force_mode', False) else "bioag"
                
                def term_task():
                    if st.session_state.bypass_mode: stop_bypass_task(out_queue)
                    else: stop_container_task(docker_prefix, container_name, out_queue)

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
                            except Exception as e: st.error(f"Error terminating process: {e}")
                        if col_n.button("No, cancel"): st.rerun()
                    else: st.error("Unable to identify the process occupying the port. Please free the port manually.")
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
                container_name = f"bioag_{params['bioag_port']}" if st.session_state.get('force_mode', False) else CONTAINER_NAME
                
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
                            params["gemini_mode"], params['bioag_port'], container_name, params["res_cache"], params['random_key'], params['allow_network'], 
                            params['local_storage']
                        )
                    else:
                        start_bypass(
                            params["front_ui"], params["configure"], params["conda_meta"],
                            params["workflow"], params["user_ext"], params["cache"], params["proxy"],
                            params["enable_gpu"], output_queue, params["user_name"], params["user_password"],
                            params["gemini_mode"], params['bioag_port'], params['allow_network'], 
                            params['local_storage']
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
                            if line.startswith("SUCCESS:") or line.startswith("Local URL:") or line.startswith("URL:"):
                                final_success = True
                            elif line.startswith("Initialization:"):
                                try: st.session_state.bypass_mode_pid = int(line.split(":")[1])
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
