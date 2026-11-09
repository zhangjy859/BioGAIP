import argparse
import base64
import hashlib
import json
import os
import shlex
import ssl
import sys
import time
import urllib.request
from urllib.error import URLError

import certifi
import paramiko
from paramiko.ssh_exception import NoValidConnectionsError, SSHException

build_docker_from_source = os.getenv("BIOGEN_BUILD_DOCKER_FROM_SOURCE", "1") == "1"
TARGET_BIOAGVARSION = "1.3.0.10"
CONFIG_JSON = "https://dataweb.biogaip.top/server_aws.config?expires=10414438925&token=42e159c5957d860b45685afb9eedd87d778a403dbd417c228b0624b3b9981249"
ENCRYPTION_KEY = "xD7WU2JVDrQal9"


def _xor_decrypt(b64_str: str, key: str) -> str:
    """Decrypt a configuration value."""
    if not key:
        raise ValueError("decrypt_key cannot be empty")
    encrypted = base64.b64decode(b64_str)
    key_bytes = key.encode("utf-8")
    return bytes(
        byte ^ key_bytes[index % len(key_bytes)]
        for index, byte in enumerate(encrypted)
    ).decode("utf-8")


def parse_bio_config(
    json_source: str,
    total_version: str,
    decrypt_key: str,
    max_size: int = 2_097_152,
) -> dict:
    """Load and decrypt a bounded BioWorker configuration."""
    if json_source.startswith("https://"):
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            request = urllib.request.Request(
                json_source,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
            with urllib.request.urlopen(
                request, timeout=15, context=context
            ) as response:
                length = response.headers.get("content-length")
                if length and int(length) > max_size:
                    raise ValueError("JSON response too large")
                raw = response.read(max_size + 1)
                if len(raw) > max_size:
                    raise ValueError("JSON response too large")
                config = json.loads(raw.decode("utf-8"))
        except URLError as exc:
            raise ValueError(f"Failed to fetch URL: {exc}") from exc
    else:
        if not os.path.isfile(json_source):
            raise FileNotFoundError(f"JSON file not found: {json_source}")
        if os.path.getsize(json_source) > max_size:
            raise ValueError("JSON file too large")
        with open(json_source, encoding="utf-8") as file:
            config = json.load(file)

    if total_version not in config:
        raise ValueError(f"Total version '{total_version}' not found")

    result = {}
    for name in ("BioAG", "BioWorker"):
        item = config[total_version][name]
        result[name] = {
            "version": item["version"],
            "update_url": _xor_decrypt(item["update_url"], decrypt_key),
            "update_url2": _xor_decrypt(item["update_url2"], decrypt_key),
            "tag": _xor_decrypt(item["tag"], decrypt_key),
        }
    return result


try:
    bioagworker_config = parse_bio_config(
        CONFIG_JSON, TARGET_BIOAGVARSION, ENCRYPTION_KEY, 2048
    )
    bioworker_url = bioagworker_config["BioWorker"]["update_url"]
except Exception as exc:
    print(f"Error parsing config: {exc}", file=sys.stderr, flush=True)
    bioworker_url = "https://dataweb.biogaip.top/data/bioworker_latest.tar.gz?expires=2647159118&token=4db324c25c9dd682ffe8721ce61f2f1fc78893fcd9bca4d7863f9386d949998b"


def _directory(value, label):
    """Reject characters that commonly corrupt remote directory arguments."""
    if not value:
        return value
    if (
        "\ufffd" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or value[0] in "\"'\u201c\u201d\u2018\u2019"
        or value[-1] in "\"'\u201c\u201d\u2018\u2019"
    ):
        raise ValueError(
            f"Invalid {label}: {value!a}. Re-enter the path without "
            "surrounding quotes or hidden characters."
        )
    return value


def _directories(value, label):
    return ";".join(_directory(path, label) for path in value.split(";"))


def _remote_command(ssh, command):
    """Execute a remote command with stable, ASCII-compatible diagnostics."""
    _, stdout, stderr = ssh.exec_command(f"export LC_ALL=C; {command}")
    status = stdout.channel.recv_exit_status()
    return (
        status,
        stdout.read().decode("utf-8", errors="replace").strip(),
        stderr.read().decode("utf-8", errors="replace").strip(),
    )


def exec_command(ssh, command):
    """Run a remote command and report failures without exposing its arguments."""
    status, _, error = _remote_command(ssh, command)
    if status:
        raise RuntimeError(
            f"Remote command exited with code {status}: "
            f"{error or 'no error output'}"
        )


def _directory_diagnostics(ssh, path):
    """Inspect the parent directory and its mount without modifying them."""
    parent = os.path.dirname(path.rstrip("/")) or "/"
    quoted_parent = shlex.quote(parent)
    checks = (
        ("Identity", "id"),
        ("Parent", f"stat -c '%A %U:%G %n' -- {quoted_parent}"),
        (
            "Filesystem",
            f"findmnt -T {quoted_parent} -no TARGET,FSTYPE,OPTIONS",
        ),
    )
    details = []
    for label, command in checks:
        try:
            status, output, error = _remote_command(ssh, command)
            details.append(
                f"{label}: {output if status == 0 else error or 'unavailable'}"
            )
        except (OSError, SSHException):
            details.append(f"{label}: unavailable")
    return "\n".join(details)


def mkdir_remote(ssh, path):
    """Create a remote directory or explain why its filesystem rejected it."""
    path = _directory(path, "remote directory")
    status, _, error = _remote_command(
        ssh, f"mkdir -p -- {shlex.quote(path)}"
    )
    if status == 0:
        return

    diagnostics = _directory_diagnostics(ssh, path)
    hint = (
        "\nThe remote filesystem rejected directory creation. "
        "If this is a mounted output directory, verify that it supports "
        "mkdir and is writable, or select a different temporary/working "
        "directory."
        if "Invalid argument" in error
        else ""
    )
    raise RuntimeError(
        f"Cannot create remote directory {path!r}: "
        f"{error or f'exit code {status}'}\n{diagnostics}{hint}"
    )


def get_mamba_cmd(ssh, home):
    """Find or install a remote Conda-compatible package manager."""
    for tool in ("micromamba", "mamba", "conda"):
        status, output, _ = _remote_command(ssh, f"which {tool}")
        if status == 0 and output:
            return output, tool

    _, os_type, _ = _remote_command(ssh, "uname -s")
    _, arch, _ = _remote_command(ssh, "uname -m")
    platforms = {
        ("linux", "x86_64"): "linux-64",
        ("linux", "aarch64"): "linux-aarch64",
        ("linux", "ppc64le"): "linux-ppc64le",
        ("darwin", "x86_64"): "osx-64",
        ("darwin", "arm64"): "osx-arm64",
    }
    platform_name = platforms.get((os_type.lower(), arch))
    if not platform_name:
        raise RuntimeError(f"Unsupported platform: {os_type}/{arch}")

    bin_dir = f"{home}/.bioGen/bin"
    mkdir_remote(ssh, bin_dir)
    exec_command(
        ssh,
        f"cd {shlex.quote(bin_dir)} && "
        f"curl -Ls https://micro.mamba.pm/api/micromamba/"
        f"{platform_name}/latest | tar -xvj bin/micromamba",
    )
    return f"{bin_dir}/micromamba", "micromamba"


def build_sandbox_mounts(
    ro_dir, rw_dir, work_dir, home, sandbox_type, temp_dir=None
):
    """Build quoted sandbox mount arguments."""
    flags = []
    ro_dirs = [path for path in ro_dir.split(";") if path]
    rw_dirs = [path for path in rw_dir.split(";") if path]
    quote = shlex.quote

    if sandbox_type == "bubblewrap":
        flags.extend(
            [
                "--ro-bind /usr /usr",
                "--ro-bind /lib /lib",
                "--ro-bind /lib64 /lib64",
                "--ro-bind /bin /bin",
                "--ro-bind /sbin /sbin",
                "--ro-bind /etc /etc",
                "--dev-bind /dev /dev",
                "--proc /proc",
                "--tmpfs /tmp",
                f"--bind {quote(home)} {quote(home)}",
            ]
        )
        flags.extend(
            f"--ro-bind {quote(path)} {quote(path)}" for path in ro_dirs
        )
        flags.extend(f"--bind {quote(path)} {quote(path)}" for path in rw_dirs)
        if work_dir and work_dir not in home:
            flags.append(f"--bind {quote(work_dir)} {quote(work_dir)}")
        if temp_dir and temp_dir not in home:
            flags.append(f"--bind {quote(temp_dir)} {quote(temp_dir)}")
        flags.extend(
            [
                "--unshare-pid",
                "--unshare-uts",
                "--unshare-ipc",
                "--unshare-cgroup",
                "--new-session",
                "--die-with-parent",
            ]
        )
    elif sandbox_type == "landlock":
        flags.extend(
            [
                "--unrestricted-network",
                "--rox /usr",
                "--rox /lib",
                "--rox /lib64",
                "--rox /bin",
                "--rox /sbin",
                "--ro /etc",
                f"--rwx {quote(home)}",
            ]
        )
        flags.extend(f"--ro {quote(path)}" for path in ro_dirs)
        flags.extend(f"--rw {quote(path)}" for path in rw_dirs)
        if work_dir and work_dir not in home:
            flags.append(f"--rw {quote(work_dir)}")
        if temp_dir and temp_dir not in home:
            flags.append(f"--rw {quote(temp_dir)}")
        flags.extend(["--ldd", "--add-exec"])

    return " ".join(flags)


def check_docker(ssh):
    """Check whether Docker can run containers."""
    if _remote_command(ssh, "docker --version")[0] != 0:
        print("Docker is not installed on the remote server.", flush=True)
        return False
    if _remote_command(
        ssh, "docker run --rm hello-world > /dev/null 2>&1"
    )[0] != 0:
        print("Docker is not running properly on the remote server.", flush=True)
        return False
    return True


def check_singularity(ssh):
    """Check whether Singularity is available."""
    if _remote_command(
        ssh, "singularity --version > /dev/null 2>&1"
    )[0] != 0:
        print("Singularity is not installed on the remote server.", flush=True)
        return False
    return True


def is_port_occupied(ssh, port):
    return _remote_command(
        ssh, f"lsof -i :{int(port)} > /dev/null 2>&1"
    )[0] == 0


def build_volume_string(ro_dir, rw_dir, work_dir, docker=True):
    """Build quoted container volume arguments."""
    flag = "-v" if docker else "-B"
    permissions = {}
    order = []

    for source, permission in ((ro_dir, "ro"), (rw_dir, "rw")):
        for path in source.split(";"):
            if not path:
                continue
            if path not in permissions:
                order.append(path)
            if permission == "rw" or permissions.get(path) != "rw":
                permissions[path] = permission

    flags = []
    for path in order:
        suffix = ":ro" if permissions[path] == "ro" else ""
        flags.append(f"{flag} {shlex.quote(f'{path}:{path}{suffix}')}")

    if work_dir:
        flags.append(f"{flag} {shlex.quote(f'{work_dir}:/data/work_dir')}")
        history = os.path.join(work_dir, "cmd_history")
        flags.append(f"{flag} {shlex.quote(f'{history}:/app/cmd_history')}")
    return " ".join(flags)


def copy_directory(ssh, local_dir, remote_dir):
    """Copy a local directory tree through SFTP."""
    sftp = ssh.open_sftp()
    local_dir = os.path.normpath(local_dir)
    try:
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            pass

        for root, dirs, files in os.walk(local_dir):
            remote_root = os.path.normpath(
                os.path.join(remote_dir, os.path.relpath(root, local_dir))
            ).replace("\\", "/")
            for directory in dirs:
                try:
                    sftp.mkdir(
                        os.path.join(remote_root, directory).replace("\\", "/")
                    )
                except IOError:
                    pass
            for filename in files:
                remote_file = os.path.join(
                    remote_root, filename
                ).replace("\\", "/")
                try:
                    sftp.mkdir(os.path.dirname(remote_file))
                except IOError:
                    pass
                sftp.put(os.path.join(root, filename), remote_file)
    finally:
        sftp.close()


def main():
    """Parse setup options and start the remote server."""
    parser = argparse.ArgumentParser(
        description="Setup bioGen API server on remote host."
    )
    parser.add_argument("server_ip", help="Server IP address")
    parser.add_argument("username", help="SSH username")
    parser.add_argument("port", type=int, help="SSH port")
    parser.add_argument("ssh_password", help="SSH password")
    parser.add_argument("api_key", help="API key")
    parser.add_argument("ro_dir", help="Read-only directories, separated by ';'")
    parser.add_argument("rw_dir", help="Read-write directories, separated by ';'")
    parser.add_argument("work_dir", help="Work directory")
    parser.add_argument(
        "allow_raw",
        nargs="?",
        default="0",
        help="Allow raw Python execution (1 or 0)",
    )
    parser.add_argument(
        "--user_sandbox",
        choices=["bubblewrap", "landlock"],
        default=None,
    )
    parser.add_argument("--bioworker_port", default=38000, type=int)
    parser.add_argument("--temp_dir", default=None)
    parser.add_argument("--max_task", default=1, type=int)
    parser.add_argument("--web_admin", default=False, type=bool)
    args = parser.parse_args()

    try:
        args.ro_dir = _directories(args.ro_dir, "read-only directory")
        args.rw_dir = _directories(args.rw_dir, "read-write directory")
        args.work_dir = _directory(args.work_dir, "working directory")
        args.temp_dir = _directory(args.temp_dir, "temporary directory")
    except ValueError as exc:
        parser.error(str(exc))

    allow_raw = args.allow_raw == "1"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    web_api_file = os.path.join(
        script_dir, "web_shell", "web_shell_command_v7.py"
    )
    singularity_sif = os.path.join(script_dir, "biogen_worker.sif")

    print("loading...0%", flush=True)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("ssh client created...5%", flush=True)

    try:
        try:
            ssh.connect(
                args.server_ip,
                port=args.port,
                username=args.username,
                password=args.ssh_password,
                timeout=20,
                auth_timeout=20,
                banner_timeout=20,
            )
        except (SSHException, NoValidConnectionsError, OSError) as exc:
            raise RuntimeError(
                f"Failed to connect to remote server: {exc}"
            ) from exc

        print("%10% Successfully connected to remote server.", flush=True)
        status, home, error = _remote_command(ssh, 'printf "%s" "$HOME"')
        if status or not home or "\ufffd" in home:
            raise RuntimeError(
                f"Invalid remote home directory: {home!r}; {error}"
            )
        print(f"Remote home path: {home}", flush=True)
        print("%20% Successfully connected to remote server.", flush=True)

        docker_installed = check_docker(ssh)
        singularity_installed = (
            check_singularity(ssh) if not docker_installed else False
        )

        if args.user_sandbox is not None:
            print("%30% Sandbox mode selected.", flush=True)
            mkdir_remote(ssh, f"{home}/bioGen")

            remote_path = f"{home}/bioGen/web_shell_command_v8.py"
            sftp = ssh.open_sftp()
            try:
                sftp.put(web_api_file, remote_path)
            finally:
                sftp.close()
            print("%50% Sync local files.", flush=True)

            if args.user_sandbox == "bubblewrap":
                tool_name = "bwrap"
                package = "bubblewrap"
                default_path = "bwrap"
                status, tool_path, _ = _remote_command(ssh, "which bwrap")
            else:
                tool_name = "landrun"
                package = "go"
                default_path = f"{home}/.bioGen/go/bin/landrun"
                status, tool_path, _ = _remote_command(
                    ssh,
                    f"test -x {shlex.quote(default_path)} "
                    f"&& printf '%s' {shlex.quote(default_path)}",
                )

            if status == 0 and tool_path:
                sandbox_cmd = shlex.quote(tool_path)
            else:
                mamba_path, _ = get_mamba_cmd(ssh, home)
                env_prefix = f"{home}/.bioGen/sandbox_{args.user_sandbox}"
                exec_command(
                    ssh,
                    f"{shlex.quote(mamba_path)} create "
                    f"-p {shlex.quote(env_prefix)} -y",
                )
                exec_command(
                    ssh,
                    f"{shlex.quote(mamba_path)} install "
                    f"-p {shlex.quote(env_prefix)} "
                    f"-c conda-forge {package} -y",
                )
                if args.user_sandbox == "landlock":
                    _, gopath, _ = _remote_command(
                        ssh,
                        f"{shlex.quote(mamba_path)} run "
                        f"-p {shlex.quote(env_prefix)} go env GOPATH",
                    )
                    default_path = (
                        f"{gopath or f'{home}/.bioGen/go'}/bin/landrun"
                    )
                    exec_command(
                        ssh,
                        f"{shlex.quote(mamba_path)} run "
                        f"-p {shlex.quote(env_prefix)} go install "
                        "github.com/zouuup/landrun/cmd/landrun@latest",
                    )
                    status, _, _ = _remote_command(
                        ssh, f"test -x {shlex.quote(default_path)}"
                    )
                    if status:
                        raise RuntimeError("Failed to install landrun")

                sandbox_cmd = (
                    f"{shlex.quote(mamba_path)} run "
                    f"-p {shlex.quote(env_prefix)} {tool_name}"
                    if args.user_sandbox == "bubblewrap"
                    else shlex.quote(default_path)
                )

            print("%60% Sandbox tool ready.", flush=True)
            work_dir = args.work_dir or f"{home}/bioGen/work_dir"
            mkdir_remote(ssh, work_dir)
            mkdir_remote(ssh, f"{work_dir}/cmd_history")
            if args.temp_dir:
                mkdir_remote(ssh, args.temp_dir)

            api_port = int(
                os.getenv("BIOWORKER_PORT", str(args.bioworker_port))
            )
            if is_port_occupied(ssh, api_port):
                raise RuntimeError(
                    f"Port {api_port} is already in use on the remote server."
                )

            mounts = build_sandbox_mounts(
                args.ro_dir,
                args.rw_dir,
                work_dir,
                home,
                args.user_sandbox,
                temp_dir=args.temp_dir,
            )
            command = (
                f"export API_KEY={shlex.quote(args.api_key)} && "
                f"export WORK_DIR={shlex.quote(work_dir)} && "
                f"export BIOWORKER_PORT={api_port} && "
                f"export MAX_TASK={args.max_task} && "
                f"export ENABLE_ADMIN_PANEL="
                f"{shlex.quote(str(args.web_admin))} && "
                f"nohup {sandbox_cmd} {mounts} "
                f"python3 {shlex.quote(remote_path)} "
                "> /dev/null 2>&1 &"
            )
            exec_command(ssh, command)
            print("%100% Executed remote command.", flush=True)
            print(
                f"Successfully started bioGen API server with "
                f"{args.user_sandbox} on {args.server_ip}:{api_port}",
                flush=True,
            )
            return

        if not docker_installed and not singularity_installed and not allow_raw:
            install_url = (
                "https://raw.githubusercontent.com/zhangjy859/"
                "rstudio-server-conda-singularity/refs/heads/main/"
                "install_singularity.sh"
            )
            print(
                "Neither Docker nor Singularity is available. "
                "Trying to install Singularity.",
                flush=True,
            )
            exec_command(
                ssh,
                "wget -O /tmp/install_singularity.sh "
                f"{shlex.quote(install_url)} && "
                "bash /tmp/install_singularity.sh "
                "/tmp/singularity $HOME/.bioGen/singularity true",
            )
            singularity_installed = check_singularity(ssh)
            if not singularity_installed:
                raise RuntimeError(
                    "Failed to install Singularity. Install Docker or "
                    "Singularity manually, or allow raw Python execution."
                )

        print("%30% Environment check completed.", flush=True)
        mkdir_remote(ssh, f"{home}/bioGen")
        print("%40% Prepared remote directories.", flush=True)

        if not docker_installed and not singularity_installed and allow_raw:
            remote_path = f"{home}/bioGen/web_shell_command_v7.py"
            sftp = ssh.open_sftp()
            try:
                sftp.put(web_api_file, remote_path)
            finally:
                sftp.close()
            print("%50% Sync local files.", flush=True)
            exec_command(
                ssh,
                f"export API_KEY={shlex.quote(args.api_key)} && "
                f"nohup python3 {shlex.quote(remote_path)} "
                "> /dev/null 2>&1 &",
            )
            print("%100% Executed remote command.", flush=True)
            print(
                f"Successfully started bioGen API server with python "
                f"script on {args.server_ip}:38000",
                flush=True,
            )
            return

        if docker_installed:
            print("Cleaning existing environment", flush=True)
            mkdir_remote(ssh, f"{home}/bioGen/bioWorker")
            exec_command(
                ssh,
                "docker stop bioworker > /dev/null 2>&1 || true",
            )
            time.sleep(3)
            exec_command(
                ssh,
                "docker rm bioworker > /dev/null 2>&1 || true",
            )
            print("%60% Cleaned existing Docker containers.", flush=True)
            print(
                "%60% Pull latest bioworker; this may take 5 to 10 minutes.",
                flush=True,
            )

            use_backup = True
            try:
                exec_command(
                    ssh,
                    "docker pull 10.157.66.19:5000/bioworker:latest",
                )
                exec_command(
                    ssh,
                    "docker tag 10.157.66.19:5000/bioworker:latest "
                    "bioworker:latest",
                )
                print(
                    "%70% Pulled docker image from internal registry.",
                    flush=True,
                )
                use_backup = False
            except RuntimeError:
                print(
                    "Failed to pull from the internal registry; "
                    "using the backup image.",
                    flush=True,
                )

            if is_port_occupied(ssh, args.bioworker_port):
                raise RuntimeError(
                    f"Port {args.bioworker_port} is already in use."
                )

            if use_backup:
                print("%70% Download from backup server. This may take more time.", flush=True)
                archive = f"{home}/bioGen/bioWorker/bioworker_latest.tar.gz"
                exec_command(
                    ssh,
                    f"wget -O {shlex.quote(archive)} "
                    f"-q {shlex.quote(bioworker_url)}",
                )
                exec_command(
                    ssh, f"docker load -i {shlex.quote(archive)}"
                )
                try:
                    exec_command(ssh, f"rm -- {shlex.quote(archive)}")
                except RuntimeError:
                    print(
                        f"Failed to remove image archive: {archive}",
                        flush=True,
                    )

            volumes = build_volume_string(
                args.ro_dir,
                args.rw_dir,
                args.work_dir,
                docker=True,
            )
            if args.temp_dir:
                mkdir_remote(ssh, args.temp_dir)
                volumes += (
                    f" -v {shlex.quote(f'{args.temp_dir}:{args.temp_dir}')}"
                    f" -v {shlex.quote(f'{args.temp_dir}:/tmp')}"
                )
            if args.work_dir:
                mkdir_remote(
                    ssh, os.path.join(args.work_dir, "cmd_history")
                )

            print(
                "Starting Docker container on remote server...",
                flush=True,
            )
            try:
                with open(
                    "/proc/sys/kernel/random/boot_id", encoding="utf-8"
                ) as file:
                    salt = file.read().strip()
            except OSError:
                salt = ""

            name_hash = hashlib.md5(
                (str(args.bioworker_port) + salt).encode()
            ).hexdigest()[:10]
            name = f"bioworker_{name_hash}"
            command = (
                f"docker run -d --rm --name {name} "
                f"-e API_KEY={shlex.quote(args.api_key)} "
                f"-e BIOWORKER_PORT={args.bioworker_port} "
                f"-e MAX_TASK={args.max_task} "
                f"-e ENABLE_ADMIN_PANEL="
                f"{shlex.quote(str(args.web_admin))} "
                "--user $(id -u):$(id -g) "
                f"-p {args.bioworker_port}:{args.bioworker_port} "
                "--cap-drop SETUID --cap-drop SETGID "
                "--security-opt=no-new-privileges "
                f"{volumes} bioworker:latest"
            )
            exec_command(ssh, command)
            print(
                "%80% Successfully started Docker container.",
                flush=True,
            )
            time.sleep(10)
            print("%100% Executed remote command.", flush=True)
            print(
                f"Successfully started bioGen API server in docker "
                f"on {args.server_ip}:{args.bioworker_port}",
                flush=True,
            )
            return

        if singularity_installed:
            remote_script = f"{home}/bioGen/web_shell_command_v5.py"
            remote_sif = f"{home}/bioGen/biogen_worker.sif"
            sftp = ssh.open_sftp()
            try:
                sftp.put(web_api_file, remote_script)
                print("%50% Sync local files.", flush=True)
                sftp.put(singularity_sif, remote_sif)
            finally:
                sftp.close()
            print("%60% Sync local files.", flush=True)

            if is_port_occupied(ssh, args.bioworker_port):
                raise RuntimeError(
                    f"Port {args.bioworker_port} is already in use."
                )

            volumes = build_volume_string(
                args.ro_dir,
                args.rw_dir,
                args.work_dir,
                docker=False,
            )
            if args.work_dir:
                mkdir_remote(
                    ssh, os.path.join(args.work_dir, "cmd_history")
                )
            if args.temp_dir:
                mkdir_remote(ssh, args.temp_dir)
                volumes += (
                    f" -B {shlex.quote(f'{args.temp_dir}:{args.temp_dir}')}"
                    f" -B {shlex.quote(f'{args.temp_dir}:/tmp')}"
                )

            command = (
                f"export API_KEY={shlex.quote(args.api_key)} && "
                f"export BIOWORKER_PORT={args.bioworker_port} && "
                f"export MAX_TASK={args.max_task} && "
                f"export ENABLE_ADMIN_PANEL="
                f"{shlex.quote(str(args.web_admin))} && "
                f"nohup singularity exec {volumes} "
                f"{shlex.quote(remote_sif)} python3 "
                f"{shlex.quote(remote_script)} > /dev/null 2>&1 &"
            )
            exec_command(ssh, command)
            print("%100% Executed remote command.", flush=True)
            print(
                f"Successfully started bioGen API server with singularity "
                f"on {args.server_ip}:{args.bioworker_port}",
                flush=True,
            )
            return

        raise RuntimeError(
            "No suitable execution environment found on the remote server."
        )
    except (RuntimeError, ValueError, OSError, SSHException) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()