import argparse
import os
import sys
import time
import hashlib
import base64
import json
import urllib
from urllib.request import urlopen
from urllib.error import URLError
import ssl
import certifi
import platform
import paramiko
from paramiko.ssh_exception import SSHException, NoValidConnectionsError

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "1") == "1"
TARGET_BIOAGVARSION = "1.3.0.10"
CONFIG_JSON = "https://dataweb.biogaip.top/server_aws.config?expires=10414438925&token=42e159c5957d860b45685afb9eedd87d778a403dbd417c228b0624b3b9981249"
ENCRYPTION_KEY = 'xD7WU2JVDrQal9'

def _xor_decrypt(b64_str: str, key: str) -> str:
    if not key:
        raise ValueError("decrypt_key cannot be empty")
    encrypted = base64.b64decode(b64_str)
    key_bytes = key.encode("utf-8")
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")

def parse_bio_config(json_source: str, total_version: str, decrypt_key: str, max_size: int = 2_097_152) -> dict:
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

    return {"BioAG": bioag, "BioWorker": bioworker}

try:
    bioagworker_config = parse_bio_config(CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048)
    bioworker_url = bioagworker_config['BioWorker']['update_url']
except Exception as e:
    sys.stderr.write(f"Error parsing config: {e}\n")
    bioworker_url = "https://dataweb.biogaip.top/data/bioworker_latest.tar.gz?expires=1783077728&token=e113d2386024395b8714396df7b2f84c8580857eaccbdafafc22b21adb310be2"

def main():
    parser = argparse.ArgumentParser(description="Setup bioGen API server on remote host.")
    parser.add_argument("server_ip", help="Server IP address")
    parser.add_argument("username", help="SSH username")
    parser.add_argument("port", type=int, help="SSH port")
    parser.add_argument("ssh_password", help="SSH password")
    parser.add_argument("api_key", help="API key")
    parser.add_argument("ro_dir", help="Read-only directories, separated by ';'")
    parser.add_argument("rw_dir", help="Read-write directories, separated by ';'")
    parser.add_argument("work_dir", help="Work directory")
    parser.add_argument("allow_raw", nargs="?", default="0", help="Allow raw Python execution (1 or 0)")
    parser.add_argument("--user_sandbox", choices=["bubblewrap", "landlock"], help="Sandbox mode: bubblewrap or landlock", default=None)
    parser.add_argument("bioworker_port", default=38000, help="Bioworker port")

    args = parser.parse_args()
    allow_raw = 1 if args.allow_raw == "1" else 0

    script_dir = os.path.dirname(os.path.abspath(__file__))
    web_api_file = os.path.join(script_dir, "web_shell_command_v5.py")
    web_api_docker = os.path.join(script_dir, "..", "docker", "bioWorker")
    singularity_sif = os.path.join(script_dir, "biogen_worker.sif")

    # Establish SSH connection
    print('loading...0%')
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    except Exception as e:
        print(f"Failed to create SSH client: {e}")
        sys.exit(1)
    finally:
        print('ssh client created...5%')
    try:
        ssh.connect(args.server_ip, port=args.port, username=args.username, password=args.ssh_password)
        print("%10%", "Successfully connected to remote server.")
    except (SSHException, NoValidConnectionsError) as e:
        print(f"Failed to connect to remote server: {e}")
        sys.exit(1)

    # get home path remotely
    _, stdout, _ = ssh.exec_command("echo $HOME")
    home = stdout.read().decode().strip()
    print(f"Remote home path: {home}")

    print("%20%", "Successfully connected to remote server.")

    # Check Docker
    docker_installed = check_docker(ssh)

    # Check Singularity if Docker not available
    singularity_installed = False
    if not docker_installed:
        singularity_installed = check_singularity(ssh)

    if args.user_sandbox is not None:
        print("%30%", "Sandbox mode selected.")

        exec_command(ssh, "mkdir -p ~/bioGen")
        sftp = ssh.open_sftp()
        remote_path = f"{home}/bioGen/web_shell_command_v5.py"
        sftp.put(web_api_file, remote_path)
        sftp.close()
        print("%50%", "Sync local files.")

        if args.user_sandbox == "bubblewrap":
            tool_name = "bwrap"
            package = "bubblewrap"
            channel = "conda-forge"
            default_path = "bwrap"
        elif args.user_sandbox == "landlock":
            tool_name = "landrun"
            package = "go"
            channel = "conda-forge"
            default_path = f"{home}/.bioGen/go/bin/landrun"

        # Check if sandbox tool is available
        if args.user_sandbox == "bubblewrap":
            _, stdout, _ = ssh.exec_command(f"which {tool_name}")
        else:
            _, stdout, _ = ssh.exec_command(f"[ -x {default_path} ] && echo {default_path}")
        tool_path = stdout.read().decode().strip()

        if tool_path:
            sandbox_cmd = tool_path
        else:
            # Install
            mamba_path, _ = get_mamba_cmd(ssh, home)
            env_prefix = f"{home}/.bioGen/sandbox_{args.user_sandbox}"
            exec_command(ssh, f"{mamba_path} create -p {env_prefix} -y")
            exec_command(ssh, f"{mamba_path} install -p {env_prefix} -c {channel} {package} -y")
            if args.user_sandbox == "landlock":
                _, stdout, _ = ssh.exec_command(f"{mamba_path} run -p {env_prefix} go env GOPATH")
                gopath = stdout.read().decode().strip()
                if not gopath:
                    gopath = f"{home}/.bioGen/go"
                default_path = f"{gopath}/bin/landrun"
                exec_command(ssh, f"{mamba_path} run -p {env_prefix} go install github.com/zouuup/landrun/cmd/landrun@latest")
                _, stdout, _ = ssh.exec_command(f"[ -x {default_path} ] && echo {default_path}")
                tool_path = stdout.read().decode().strip()
                if not tool_path:
                    print("Failed to install landrun")
                    sys.exit(1)
            if args.user_sandbox == "bubblewrap":
                sandbox_cmd = f"{mamba_path} run -p {env_prefix} {tool_name}"
            else:
                sandbox_cmd = default_path

        print("%60%", "Sandbox tool ready.")

        # Prepare work_dir
        if args.work_dir:
            work_dir = args.work_dir
        else:
            work_dir = f"{home}/bioGen/work_dir"
        exec_command(ssh, f"mkdir -p {work_dir}")
        cmd_history = f"{work_dir}/cmd_history"
        exec_command(ssh, f"mkdir -p {cmd_history}")

        # Check port
        api_port = os.getenv("BIOWORKER_PORT", str(args.bioworker_port))
        if is_port_occupied(ssh, int(api_port)):
            print(f"Port {api_port} is already in use on the remote server. Please free the port and try again.")
            sys.exit(1)

        # Build mounts
        mounts_str = build_sandbox_mounts(args.ro_dir, args.rw_dir, work_dir, home, args.user_sandbox)

        run_cmd = (
            f"export API_KEY='{args.api_key}' && "
            f"export WORK_DIR='{work_dir}' && "
            f"export BIOWORKER_PORT='{api_port}' && "
            f"nohup {sandbox_cmd} {mounts_str} python3 {remote_path} > /dev/null 2>&1 &"
        )
        exec_command(ssh, run_cmd)
        print("%100%", "Executed remote command.")
        print(f"Successfully started bioGen API server with {args.user_sandbox} on {args.server_ip}:{api_port}")
        sys.exit(0)

    if not docker_installed and not singularity_installed and not allow_raw:
        print("Neither Docker nor Singularity is available on the remote server, and raw Python execution is not allowed.")
        singularity_install_url="https://raw.githubusercontent.com/zhangjy859/rstudio-server-conda-singularity/refs/heads/main/install_singularity.sh"
        ## download script and Usage: $0 <tmp_dir> <install_path> [use_mirror]
        print(f"Non supported environment. Will try auto install Singularity from {singularity_install_url}")
        exec_command(ssh, f"wget -O /tmp/install_singularity.sh {singularity_install_url} && bash /tmp/install_singularity.sh /tmp/singularity $HOME/.bioGen/singularity true")
        singularity_installed = check_singularity(ssh)
        if not singularity_installed:
            print("Failed to install Singularity on the remote server. Please install Docker or Singularity manually, or allow raw Python execution.")
            sys.exit(2)

    print("%30%", "Environment check completed.")

    # Prepare directories on remote
    exec_command(ssh, "mkdir -p ~/bioGen")

    print("%40%", "Prepared remote directories.")

    if not docker_installed and not singularity_installed and allow_raw:
        # Raw Python mode
        exec_command(ssh, "mkdir -p ~/bioGen")
        sftp = ssh.open_sftp()
        remote_path = f"{home}/bioGen/web_shell_command_v5.py"
        sftp.put(web_api_file, remote_path)
        sftp.close()
        print("%50%", "Sync local files.")
        # Run the script in background
        exec_command(ssh, f"export API_KEY='{args.api_key}' && nohup python3 {remote_path} > /dev/null 2>&1 &")
        print("%100%", "Executed remote command.")
        print(f"Successfully started bioGen API server with python script on {args.server_ip}:38000")
        sys.exit(0)

    elif docker_installed:
        # Docker mode
        # Copy docker directory
        #if build_docker_from_source:
        if True:
            copy_directory(ssh, web_api_docker, f"{home}/bioGen/bioWorker")
            print("%50%", "Sync local files.")
        # Clean existing environment
        print("Cleaning existing environment")
        exec_command(ssh, "mkdir -p ~/bioGen/bioWorker && cd ~/bioGen/bioWorker && docker stop bioworker > /dev/null 2>&1 || true")
        time.sleep(3)
        exec_command(ssh, "mkdir -p ~/bioGen/bioWorker && cd ~/bioGen/bioWorker && docker rm bioworker > /dev/null 2>&1 || true")

        print("%60%", "Cleaned existing Docker containers.")
        print("%60%", "Pull latest bioworker, that may take 5 to 10 minutes")

        #if not build_docker_from_source or True:
        build_docker_from_source = True
        if True:
            try:
                exec_command(ssh, "docker pull 10.157.66.19:5000/bioworker:latest")
                ## tag it
                exec_command(ssh, "docker tag 10.157.66.19:5000/bioworker:latest bioworker:latest")
                print("%70%", "Pulled docker image from internal registry.")
                build_docker_from_source = False
            except:
                print("Failed to pull docker image from internal registry, will build from source.")

        # Check port 38000
        if is_port_occupied(ssh, args.bioworker_port):
            print(f"Port {args.bioworker_port} is already in use on the remote server. Please free the port and try again.")
            sys.exit(1)

        # Build image
        if build_docker_from_source:
            print("Building Docker image on remote server...")
            print("%70%", "Download from backup server.")
            #exec_command(ssh, "mkdir -p ~/bioGen/bioWorker && cd ~/bioGen/bioWorker && docker build -t bioworker:latest .")
            exec_command(ssh, "mkdir -p ~/bioGen/bioWorker && wget -O ~/bioGen/bioWorker/bioworker_latest.tar.gz " + " -q " + f'"{bioworker_url}"')
            exec_command(ssh, "docker load -i ~/bioGen/bioWorker/bioworker_latest.tar.gz")
            try:
                exec_command(ssh, "rm ~/bioGen/bioWorker/bioworker_latest.tar.gz")
            except:
                print("Failed to remove tar.gz file, please check and remove it manually to save space: " + f"{home}/bioGen/bioWorker/bioworker_latest.tar.gz")

        # Prepare volumes
        volume_str = build_volume_string(args.ro_dir, args.rw_dir, args.work_dir, docker=True)

        ## if work_dir is given, create cmd_history folder
        if args.work_dir:
            cmd_history = os.path.join(args.work_dir, "cmd_history")
            exec_command(ssh, f"mkdir -p {cmd_history}")

        ## safety check args
        safetly_args = '--cap-drop SETUID --cap-drop SETGID --security-opt=no-new-privileges'

        # Run container
        print("Starting Docker container on remote server...")
        try:
            with open('/proc/sys/kernel/random/boot_id','r') as f: 
                salt=f.read().strip()   
        except Exception as e:
            sys.stderr.write(f'Error when get container salt{e}')
            salt=""
        bioworker_name = hashlib.md5((str(args.bioworker_port) + salt).encode()).hexdigest()[:10]
        bioworker_name = 'bioworker_' + bioworker_name 
        run_cmd = (
            f"mkdir -p ~/bioGen/bioWorker && cd ~/bioGen/bioWorker && "
            # --net host
            f"docker run -d --rm --name {bioworker_name} -e API_KEY='{args.api_key}' -e BIOWORKER_PORT='{args.bioworker_port}' --user $(id -u):$(id -g) -p {args.bioworker_port}:{args.bioworker_port} {safetly_args} {volume_str} bioworker:latest"
        )
        print(run_cmd)
        exec_command(ssh, run_cmd)

        print("%80%", "Successfully started Docker container.")

        time.sleep(10)
        print("%100%", "Executed remote command.")
        print(f"Successfully started bioGen API server in docker on {args.server_ip}:38000")
        sys.exit(0)

    elif singularity_installed:
        # Singularity mode
        sftp = ssh.open_sftp()
        # Copy Python script
        remote_script_path = f"{home}/bioGen/web_shell_command_v5.py"
        sftp.put(web_api_file, remote_script_path)
        print("%50%", "Sync localfiles.")
        # Copy SIF file
        remote_sif_path = f"{home}/bioGen/biogen_worker.sif"
        sftp.put(singularity_sif, remote_sif_path)
        sftp.close()
        print("%60%", "Sync local files.")

        # Check port 38000
        if is_port_occupied(ssh, args.bioworker_port):
            print(f"Port {args.bioworker_port} is already in use on the remote server. Please free the port and try again.")
            sys.exit(1)

        # Prepare volumes
        volume_str = build_volume_string(args.ro_dir, args.rw_dir, args.work_dir, docker=False)

        ## if work_dir is given, create cmd_history folder
        if args.work_dir:
            cmd_history = os.path.join(args.work_dir, "cmd_history")
            exec_command(ssh, f"mkdir -p {cmd_history}")

        # Run Singularity in background
        run_cmd = (
            f"export API_KEY='{args.api_key}' && "
            f"export BIOWORKER_PORT='{args.bioworker_port}' && "
            f"nohup singularity exec {volume_str} {remote_sif_path} python3 {remote_script_path} > /dev/null 2>&1 &"
        )
        exec_command(ssh, run_cmd)
        print("%100%", "Executed remote command.")
        print(f"Successfully started bioGen API server with singularity on {args.server_ip}:{args.bioworker_port}")
        sys.exit(0)

    else:
        print("No suitable execution environment found on the remote server.")
        sys.exit(9)

    ssh.close()

def get_mamba_cmd(ssh, home):
    for tool in ["micromamba", "mamba", "conda"]:
        _, stdout, _ = ssh.exec_command(f"which {tool}")
        path = stdout.read().decode().strip()
        if path:
            return path, tool

    # Download micromamba
    _, stdout, _ = ssh.exec_command("uname -s")
    os_type = stdout.read().decode().strip().lower()
    _, stdout, _ = ssh.exec_command("uname -m")
    arch = stdout.read().decode().strip()

    if os_type == "linux":
        if arch == "x86_64":
            plat = "linux-64"
        elif arch == "aarch64":
            plat = "linux-aarch64"
        elif arch == "ppc64le":
            plat = "linux-ppc64le"
        else:
            print("Unsupported architecture")
            sys.exit(1)
    elif os_type == "darwin":
        if arch == "x86_64":
            plat = "osx-64"
        elif arch == "arm64":
            plat = "osx-arm64"
        else:
            print("Unsupported architecture")
            sys.exit(1)
    else:
        print("Unsupported OS")
        sys.exit(1)

    bin_dir = f"{home}/.bioGen/bin"
    exec_command(ssh, f"mkdir -p {bin_dir}")
    download_cmd = f"cd {bin_dir} && curl -Ls https://micro.mamba.pm/api/micromamba/{plat}/latest | tar -xvj bin/micromamba"
    exec_command(ssh, download_cmd)
    return f"{bin_dir}/micromamba", "micromamba"

def build_sandbox_mounts(ro_dir, rw_dir, work_dir, home, sandbox_type):
    flags = []
    ro_dirs = [d for d in ro_dir.split(';') if d]
    rw_dirs = [d for d in rw_dir.split(';') if d]

    if sandbox_type == "bubblewrap":
        flags.extend([
            "--ro-bind /usr /usr",
            "--ro-bind /lib /lib",
            "--ro-bind /lib64 /lib64",
            "--ro-bind /bin /bin",
            "--ro-bind /sbin /sbin",
            "--ro-bind /etc /etc",
            "--dev-bind /dev /dev",
            "--proc /proc",
            "--tmpfs /tmp",
        ])
        flags.append(f"--bind {home} {home}")
        for d in ro_dirs:
            flags.append(f"--ro-bind {d} {d}")
        for d in rw_dirs:
            flags.append(f"--bind {d} {d}")
        flags.extend([
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-cgroup",
            "--new-session",
            "--die-with-parent",
        ])
    elif sandbox_type == "landlock":
        flags.append("--unrestricted-network")
        flags.extend([
            "--rox /usr",
            "--rox /lib",
            "--rox /lib64",
            "--rox /bin",
            "--rox /sbin",
            "--ro /etc",
        ])
        flags.append(f"--rwx {home}")
        for d in ro_dirs:
            flags.append(f"--ro {d}")
        for d in rw_dirs:
            flags.append(f"--rw {d}")
        if work_dir and work_dir not in home:
            flags.append(f"--rw {work_dir}")
        flags.extend(["--ldd", "--add-exec"])

    return " ".join(flags)

def check_docker(ssh):
    _, stdout, stderr = ssh.exec_command("docker --version")
    if stdout.channel.recv_exit_status() != 0:
        print("Docker is not installed on the remote server.")
        return False

    _, stdout, stderr = ssh.exec_command("docker run --rm hello-world > /dev/null 2>&1")
    if stdout.channel.recv_exit_status() != 0:
        print("Docker is not running properly on the remote server.")
        return False
    return True

def check_singularity(ssh):
    _, stdout, stderr = ssh.exec_command("singularity --version > /dev/null 2>&1")
    if stdout.channel.recv_exit_status() != 0:
        print("Singularity is not installed on the remote server.")
        return False
    return True

def is_port_occupied(ssh, port):
    _, stdout, stderr = ssh.exec_command(f"lsof -i :{port} > /dev/null 2>&1")
    return stdout.channel.recv_exit_status() == 0

def exec_command(ssh, command):
    _, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        error_output = stderr.read().decode().strip()
        sys.stdout.write(f"Command failed: {command}\nError: {error_output}")
        sys.exit(1)

def build_volume_string(ro_dir, rw_dir, work_dir, docker=True):
    flag = "-v" if docker else "-B"
    dirs_perm = {}
    dirs_order = []
    for source, perm in [(ro_dir, 'ro'), (rw_dir, 'rw')]:
        for d in source.split(';'):
            if d and d not in dirs_perm:
                dirs_order.append(d)
            if d:
                if perm == 'rw' or dirs_perm.get(d) != 'rw':
                    dirs_perm[d] = perm
    flags = []
    for d in dirs_order:
        perm = dirs_perm[d]
        if perm == 'ro':
            flags.append(f"{flag} {d}:{d}:ro")
        else:
            flags.append(f"{flag} {d}:{d}")
    if work_dir:
        flags.append(f"{flag} {work_dir}:/data/work_dir")
        cmd_history = os.path.join(work_dir, "cmd_history")
        flags.append(f"{flag} {cmd_history}:/app/cmd_history")
    return " ".join(flags).strip()

def copy_directory(ssh, local_dir, remote_dir):
    sftp = ssh.open_sftp()
    local_dir = os.path.normpath(local_dir)
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass  # Directory already exists

    for root, dirs, files in os.walk(local_dir):
        remote_root = os.path.join(remote_dir, os.path.relpath(root, local_dir)).replace("\\", "/")
        remote_root = os.path.normpath(remote_root)
        for d in dirs:
            remote_subdir = os.path.join(remote_root, d).replace("\\", "/")
            try:
                sftp.mkdir(remote_subdir)
            except IOError:
                pass
        for f in files:
            local_file = os.path.join(root, f)
            remote_file = os.path.join(remote_root, f).replace("\\", "/")
            local_file = os.path.normpath(local_file)
            print(local_file, remote_file)
            remote_dirname = os.path.dirname(remote_file)
            try:
                sftp.mkdir(remote_dirname)
            except:
                pass
            sftp.put(local_file, remote_file)
    sftp.close()

if __name__ == "__main__":
    main()