import argparse
import os
import sys
import time
import paramiko
from paramiko.ssh_exception import SSHException, NoValidConnectionsError

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "0") == "1"

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

    args = parser.parse_args()
    allow_raw = 1 if args.allow_raw == "1" else 0

    script_dir = os.path.dirname(os.path.abspath(__file__))
    web_api_file = os.path.join(script_dir, "web_shell_command_v2.py")
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
        
    if not docker_installed and not singularity_installed and not allow_raw:
        print("Neither Docker nor Singularity is available on the remote server, and raw Python execution is not allowed.")
        singularity_install_url="https://raw.githubusercontent.com/zhangjy859/rstudio-server-conda-singularity/refs/heads/main/install_singularity.sh"
        ## download script and Usage: $0 <tmp_dir> <install_path> [use_mirror]
        print(f"Non supported environment. Will try auto install Singularity from {singularity_install_url}")
        exec_command(ssh, f"wget -O /tmp/install_singularity.sh {singularity_install_url} && bash /tmp/install_singularity.sh /tmp/singularity $HOME/.local/singularity true")
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
        sftp = ssh.open_sftp()
        remote_path = f"{home}/bioGen/web_shell_command_v2.py"
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
        if build_docker_from_source:
            copy_directory(ssh, web_api_docker, f"{home}/bioGen/bioWorker")
            print("%50%", "Sync local files.")
        # Clean existing environment
        print("Cleaning existing environment")
        exec_command(ssh, "cd ~/bioGen/bioWorker && docker stop bioworker > /dev/null 2>&1 || true")
        time.sleep(3)
        exec_command(ssh, "cd ~/bioGen/bioWorker && docker rm bioworker > /dev/null 2>&1 || true")

        print("%60%", "Cleaned existing Docker containers.")

        if not build_docker_from_source:
            try:
                exec_command(ssh, "docker pull 10.157.66.19:5000/bioworker:latest")
                ## tag it
                exec_command(ssh, "docker tag 10.157.66.19:5000/bioworker:latest bioworker:latest")
                print("%70%", "Pulled docker image from internal registry.")
            except:
                print("Failed to pull docker image from internal registry, will build from source.")

        # Check port 38000
        if is_port_occupied(ssh, 38000):
            print("Port 38000 is already in use on the remote server. Please free the port and try again.")
            sys.exit(1)

        # Build image
        if build_docker_from_source:
            print("Building Docker image on remote server...")
            #exec_command(ssh, "cd ~/bioGen/bioWorker && docker build -t bioworker:latest .")
            exec_command(ssh, "docker load -i /mnt/data3/zhangjy/bioGen_test/software/bioworker_latest.tar.gz")

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
        run_cmd = (
            f"cd ~/bioGen/bioWorker && "
            #f"docker run -d --name bioworker -e API_KEY='{args.api_key}' --user $(id -u):$(id -g) --dns 1.1.1.1 --dns 8.8.8.8 -p 38000:38000   {volume_str}  bioworker:latest"
            f"docker run -d --rm --name bioworker -e API_KEY='{args.api_key}' --user $(id -u):$(id -g) {safetly_args} --net host  {volume_str}  bioworker:latest"
        )
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
        remote_script_path = f"{home}/bioGen/web_shell_command_v2.py"
        sftp.put(web_api_file, remote_script_path)
        print("%50%", "Sync localfiles.")
        # Copy SIF file
        remote_sif_path = f"{home}/bioGen/biogen_worker.sif"
        sftp.put(singularity_sif, remote_sif_path)
        sftp.close()
        print("%60%", "Sync local files.")

        # Check port 38000
        if is_port_occupied(ssh, 38000):
            print("Port 38000 is already in use on the remote server. Please free the port and try again.")
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
            f"nohup singularity exec {volume_str} {remote_sif_path} python3 {remote_script_path} > /dev/null 2>&1 &"
        )
        exec_command(ssh, run_cmd)
        print("%100%", "Executed remote command.")
        print(f"Successfully started bioGen API server with singularity on {args.server_ip}:38000")
        sys.exit(0)

    else:
        print("No suitable execution environment found on the remote server.")
        sys.exit(9)

    ssh.close()

def check_docker(ssh):
    _, stdout, stderr = ssh.exec_command("docker --version")
    if stdout.channel.recv_exit_status() != 0:
        print("Docker is not installed on the remote server.")
        return False

    _, stdout, stderr = ssh.exec_command("docker run --rm hello-world > /dev/null 2>&1")
    if stdout.channel.recv_exit_status() != 0:
        print("Docker is not running properly on the remote server.")
        return False
    #else:
    #    _, stdout, stderr = ssh.exec_command("docker stop hello-word > /dev/null 2>&1 && docker rm hello-word > /dev/null 2>&1")

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
        #if not os.path.exists(cmd_history):
        #    os.makedirs(cmd_history, exist_ok=True)
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