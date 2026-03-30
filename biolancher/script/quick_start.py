#!/usr/bin/env python3

# Script: run_container.py
# Description: Launches a container using Docker or Singularity with specified mounts and frontend.
# Usage: ./run_container.py [front_ui] [configure_file] [conda_meta_db] [workflow_db] [user_ext_db] [cache_dir] [http_proxy]
#        ./run_container.py stop
# Defaults: front_ui=CLI, others optional.

import sys
import os
import subprocess
import shutil
import tempfile

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "0") == "1"

# Container configuration
CONTAINER_IMAGE = "bioag:latest"
CONTAINER_NAME = "bioag"
MOUNT_BASE = "/data"

# Function to check if Docker is available
def check_docker():
    if shutil.which("docker"):
        return "docker"
    return None

# Function to check if Singularity is available
def check_singularity():
    if shutil.which("singularity"):
        return "singularity"
    return None

# Function to determine container engine
def get_engine():
    if check_docker():
        return "docker"
    elif check_singularity():
        return "singularity"
    else:
        print("error: Neither Docker nor Singularity is installed.", file=sys.stderr)
        sys.exit(1)

# Function to build the image if not exists (for Docker)
def build_image_if_needed(engine):
    if engine == "docker":
        image_id = subprocess.check_output(["docker", "images", "-q", CONTAINER_IMAGE]).strip()
        if not image_id:
            if not build_docker_from_source:
                try:
                    print(f"Image {CONTAINER_IMAGE} not found. Pulling from Docker Hub...")
                    subprocess.check_call(["docker", "pull", f"10.157.66.19:5000/{CONTAINER_IMAGE}"])
                    subprocess.check_call(["docker", "tag", f"10.157.66.19:5000/{CONTAINER_IMAGE}", CONTAINER_IMAGE])
                    print(f"Image {CONTAINER_IMAGE} pulled successfully.")
                    return
                except:
                    print(f"Failed to pull image {CONTAINER_IMAGE}. Will build from source.")
            print(f"Image {CONTAINER_IMAGE} not found. Building it...")
            repo_url = "xxx"  # Replace 'xxx' with the actual git repository URL
            with tempfile.TemporaryDirectory() as tmpdir:
                cwd = os.getcwd()
                os.chdir(tmpdir)
                subprocess.check_call(["git", "clone", repo_url])
                repo_name = repo_url.split('/')[-1].rstrip('.git')
                os.chdir(f"{repo_name}/docker")
                subprocess.check_call(["docker", "build", "-t", CONTAINER_IMAGE, "."])
                os.chdir(cwd)
            print(f"Image {CONTAINER_IMAGE} built successfully.")
    elif engine == "singularity":
        # TODO: Implement image check and build for Singularity
        print("Singularity image check and build not implemented.", file=sys.stderr)

# Function to start container with Docker
def start_docker(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, port=8501):
    # Build mount flags
    mounts = []
    if configure:
        mounts.extend(["-v", f"{configure}:/configure:ro"])
    if conda_meta:
        mounts.extend(["-v", f"{conda_meta}:{MOUNT_BASE}/conda_meta:rw"])
    if workflow:
        mounts.extend(["-v", f"{workflow}:{MOUNT_BASE}/pipelines_meta:rw"])
    if user_ext:
        mounts.extend(["-v", f"{user_ext}:{MOUNT_BASE}/user_ext:rw"])
    if cache:
        mounts.extend(["-v", f"{cache}:/cache"])

    port_args = f"-p {port}:{port}"

    # Environment
    envs = []
    if proxy:
        envs.extend(["--env", f"http_proxy={proxy}", "--env", f"https_proxy={proxy}"])

    # Command
    cmd_args = []
    if front_ui != "CLI":
        cmd_args.append(front_ui)

    # Run container
    command = ["docker", "run", "--rm","--name", CONTAINER_NAME] + [port_args] + mounts + envs + ["-it", CONTAINER_IMAGE] + cmd_args
    print("Running command:", ' '.join(command))
    subprocess.call(command)

# Function to start container with Singularity
def start_singularity(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy, port=8501):
    print("Singularity support is basic; adjust as needed for full mounts.", file=sys.stderr)
    # Singularity bind mounts (format: --bind host_path:container_path)
    binds = []
    if configure:
        binds.extend(["--bind", f"{configure}:/config/system_config.yaml:ro"])
    if conda_meta:
        binds.extend(["--bind", f"{conda_meta}:{MOUNT_BASE}/conda_meta:ro"])
    if workflow:
        binds.extend(["--bind", f"{workflow}:{MOUNT_BASE}/pipelines_meta:ro"])
    if user_ext:
        binds.extend(["--bind", f"{user_ext}:{MOUNT_BASE}/user_ext:ro"])
    if cache:
        binds.extend(["--bind", f"{cache}:/cache"])

    # Environment
    env_cmd = []
    if proxy:
        env_cmd.append(f"export http_proxy={proxy}")

    # Command
    cmd = []
    if front_ui != "CLI":
        cmd.append(front_ui)
    cmd.extend(env_cmd)

    # Run in background (Singularity doesn't have direct detach like Docker; use nohup or screen)
    command = ["singularity", "run"] + binds + ["--contain", "--cleanenv", "-B", "/tmp", CONTAINER_IMAGE] + cmd
    os.system("nohup " + subprocess.list2cmdline(command) + " > /dev/null 2>&1 &")

# Function to stop container
def stop_container(engine):
    if engine == "docker":
        output = subprocess.check_output(["docker", "ps", "-q", "--filter", f"name=^{CONTAINER_NAME}$"])
        if output.strip():
            subprocess.call(["docker", "stop", CONTAINER_NAME])
            subprocess.call(["docker", "rm", CONTAINER_NAME])
            print(f"Stopped and removed Docker container {CONTAINER_NAME}")
        else:
            print(f"No running Docker container named {CONTAINER_NAME}")
    elif engine == "singularity":
        # Singularity instances; adjust if using instance start
        ret = subprocess.call(["singularity", "instance", "stop", CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret != 0:
            print(f"No running Singularity instance {CONTAINER_NAME}")

# Main parameter parsing
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [front_ui] configure_file [conda_meta_db] [workflow_db] [user_ext_db] [cache_dir] [http_proxy]")
        print(f"       {sys.argv[0]} stop")
        sys.exit(1)

    if sys.argv[1] == "stop":
        engine = get_engine()
        stop_container(engine)
        sys.exit(0)

    # Run mode
    args = sys.argv[1:]

    front_ui = "CLI"
    if args and args[0] in ["streamlit", "chainlit", "CLI"]:
        front_ui = args.pop(0)

    if not args:
        print("Error: configure_file is required", file=sys.stderr)
        sys.exit(1)

    configure = args.pop(0)
    conda_meta = args.pop(0) if args else ""
    workflow = args.pop(0) if args else ""
    user_ext = args.pop(0) if args else ""
    cache = args.pop(0) if args else ""
    proxy = args.pop(0) if args else ""

    if args:
        print("Warning: Extra arguments ignored.", file=sys.stderr)

    # Validate front_ui
    if front_ui not in ["streamlit", "chainlit", "CLI"]:
        print("Error: front_ui must be 'streamlit', 'chainlit', or 'CLI'", file=sys.stderr)
        sys.exit(1)

    # Get engine
    engine = get_engine()

    # Build image if needed
    build_image_if_needed(engine)

    # Start
    if engine == "docker":
        start_docker(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy)
        print(f"Started Docker container {CONTAINER_NAME} with front_ui={front_ui}")
    elif engine == "singularity":
        start_singularity(front_ui, configure, conda_meta, workflow, user_ext, cache, proxy)
        print(f"Started Singularity instance {CONTAINER_NAME} with front_ui={front_ui}")