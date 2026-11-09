import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from queue import Empty, Queue

import requests
import streamlit as st

from bioGen.biogen import *


def shutdown_server(host=None, api_key=None):
    if not api_key or not host:
        raise ValueError("API key is required")
    response = requests.post(
        f"{host}/shutdown",
        headers={"x-api-key": api_key},
    )
    response.raise_for_status()
    return response.json()


def get_project_status(project_id, API_URL=None, API_KEY=None):
    if not project_id:
        return "No Project ID"
    try:
        response = requests.get(
            f"{API_URL}/status/project/{project_id}",
            headers={"x-api-key": API_KEY},
        )
        if response.status_code == 200:
            data = response.json()
            return json.loads(data) if isinstance(data, str) else data
        return f"Error: {response.status_code}"
    except Exception as exc:
        return f"Exception: {exc}"


def check_api(
    session_state,
    remote_tool_loaded,
    logger,
    reset_project_id=False,
    recovery=False,
):
    try:
        if (
            ("project_id" not in session_state and os.getenv("PROJECT_ID") is None)
            or reset_project_id
            or not session_state.get("project_id")
        ):
            logger.info(
                "No project_id found. Creating a project through the API."
            )
            result = asyncio.run(execute_shell_command_via_api(command=""))
            session_state["project_id"] = os.environ["PROJECT_ID"]
            if remote_tool_loaded:
                try:
                    tools = set_remote_tools(
                        tools_dict=remote_tool_detail,
                        project_id=os.environ["PROJECT_ID"],
                        api_base_url=os.environ["API_URL"],
                        api_key=os.environ["API_KEY"],
                    )
                    logger.info("set_remote_tools: %s", tools)
                except Exception as exc:
                    logger.info("biogen error: %s", exc)
            return bool(result)

        project_id = session_state.get("project_id") or os.getenv("PROJECT_ID")
        status = get_project_status(
            project_id,
            os.getenv("API_URL"),
            os.getenv("API_KEY"),
        )
        if not isinstance(status, dict):
            if recovery:
                return check_api(
                    session_state,
                    remote_tool_loaded,
                    logger,
                    reset_project_id=True,
                )
            return False
        return True
    except Exception as exc:
        st.error(f"API check failed: {exc}")
        raise


def _setup_script():
    """Prefer the existing setup path, then the installed package."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    packaged_script = os.path.join(
        os.path.dirname(script_dir),
        "ulits",
        "api_set_sandbox.py",
    )

    if os.environ.get("BIOGEN_BYPASSMODE", "").lower() == "true":
        current_script = os.path.join(
            script_dir,
            "bioag",
            "bioGen",
            "ulits",
            "api_set_sandbox.py",
        )
        return [sys.executable, "-u"], (
            current_script if os.path.isfile(current_script) else packaged_script
        )

    if sys.platform.startswith("win"):
        executable = [sys.executable, "-u"]
        filename = "api_set_sandbox.py"
    else:
        executable = ["bash"]
        filename = "api_set_warp.sh"

    candidates = [
        os.path.join(".", "bioGen", "ulits", filename),
        os.path.join("..", "bioGen", "ulits", filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return executable, path

    if os.path.isfile(packaged_script):
        return [sys.executable, "-u"], packaged_script

    return executable, candidates[-1]


def _stop_setup_process(process):
    """Stop the installer and its child processes on timeout."""
    if process.poll() is not None:
        return

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        process.wait()


def api_set2(
    server_ip,
    username,
    port,
    ssh_password,
    api_key,
    read_only_dir="",
    read_write_dir="",
    work_dir="",
    allow_raw="",
    temp_dir=None,
    bioworker_port=None,
    use_sandbox_type=None,
    max_task=1,
    web_admin=False,
):
    """Run SSH setup with live progress and bounded execution.

    BIOGEN_SSH_SETUP_TIMEOUT sets the total timeout in seconds; its
    default is 2400. BIOGEN_SSH_IDLE_TIMEOUT sets the no-output timeout;
    its default is 900.
    """
    command_prefix, script_path = _setup_script()
    command = command_prefix + [
        script_path,
        server_ip,
        username,
        str(port),
        ssh_password,
        api_key,
        read_only_dir,
        read_write_dir,
        work_dir,
        str(allow_raw),
    ]
    if use_sandbox_type:
        command += ["--user_sandbox", use_sandbox_type]
    if bioworker_port:
        command += ["--bioworker_port", str(bioworker_port)]
    if temp_dir:
        command += ["--temp_dir", temp_dir]
    command += [
        "--max_task",
        str(max_task),
        "--web_admin",
        str(web_admin),
    ]

    progress = st.progress(0, text="Starting SSH setup...")
    log_placeholder = st.empty()
    logging.getLogger(__name__).info(
        "Starting SSH setup using %s for %s:%s",
        script_path,
        server_ip,
        port,
    )

    if not os.path.isfile(script_path):
        error = f"SSH setup script not found: {script_path}"
        progress.progress(0, text="SSH setup failed")
        st.error(error)
        return False, "", error

    try:
        total_timeout = max(
            1, int(os.getenv("BIOGEN_SSH_SETUP_TIMEOUT", "2400"))
        )
        idle_timeout = max(
            1, int(os.getenv("BIOGEN_SSH_IDLE_TIMEOUT", "900"))
        )
    except ValueError:
        error = "SSH setup timeouts must be positive integers."
        progress.progress(0, text="SSH setup failed")
        st.error(error)
        return False, "", error

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        error = f"Could not start SSH setup: {exc}"
        progress.progress(0, text="SSH setup failed")
        st.error(error)
        return False, "", error

    events = Queue()

    def read_stream(stream, name):
        try:
            for raw_line in iter(stream.readline, b""):
                events.put(
                    (name, raw_line.decode("utf-8", errors="replace"))
                )
        finally:
            stream.close()
            events.put((name, None))

    for name, stream in (
        ("stdout", process.stdout),
        ("stderr", process.stderr),
    ):
        threading.Thread(
            target=read_stream,
            args=(stream, name),
            daemon=True,
        ).start()

    started = last_output = time.monotonic()
    finished_streams = set()
    output = []
    errors = []
    recent_lines = []
    started_server = False
    failure = None
    secrets_to_hide = tuple(
        value for value in (ssh_password, api_key) if value
    )

    def redact(text):
        for secret in secrets_to_hide:
            text = text.replace(secret, "[REDACTED]")
        return text

    try:
        while True:
            try:
                name, line = events.get(timeout=0.2)
            except Empty:
                name = line = None

            if name and line is None:
                finished_streams.add(name)
            elif line is not None:
                last_output = time.monotonic()
                line = redact(line)

                if name == "stdout":
                    output.append(line)
                    match = re.match(
                        r"^%(\d+)%\s*(.*)$",
                        line.strip(),
                    )
                    if match:
                        percent = min(
                            max(int(match.group(1)), 0),
                            99,
                        )
                        progress.progress(
                            percent,
                            text=match.group(2)
                            or "Setting up BioWorker...",
                        )
                    if "Successfully started bioGen API server" in line:
                        started_server = True
                else:
                    errors.append(line)

                recent_lines.append(line.rstrip("\n"))
                recent_lines = recent_lines[-80:]
                log_placeholder.code(
                    "\n".join(recent_lines)[-5000:],
                    language="text",
                )

            now = time.monotonic()
            if now - started > total_timeout:
                failure = (
                    f"SSH setup exceeded the {total_timeout}-second "
                    "total timeout."
                )
                break
            if now - last_output > idle_timeout:
                failure = (
                    f"SSH setup produced no output for {idle_timeout} "
                    "seconds. Check SSH connectivity and remote commands."
                )
                break

            if process.poll() is not None and len(finished_streams) == 2:
                break
    except BaseException:
        _stop_setup_process(process)
        raise

    if failure:
        _stop_setup_process(process)
    elif process.returncode != 0:
        failure = f"SSH setup exited with code {process.returncode}."
    elif not started_server:
        failure = (
            "SSH setup exited without confirming that the API server started."
        )

    if failure:
        progress.progress(0, text="SSH setup failed")
        st.error(failure)
        if not errors:
            errors.append(failure)
        return False, "".join(output), "".join(errors)

    progress.progress(100, text="API setup completed")
    return True, "".join(output), "".join(errors)


def pair_api_set(pair_code):
    pass


def check_model():
    model_dir = os.path.expanduser(
        "~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/"
    )
    tar_file_path = os.path.join(model_dir, "onnx.tar.gz")
    url = (
        "https://chroma-onnx-models.s3.amazonaws.com/"
        "all-MiniLM-L6-v2/onnx.tar.gz"
    )
    if os.path.exists(model_dir) and os.path.exists(tar_file_path):
        return True

    st.markdown(
        "The Embedding model file (required by RAG) is missing. "
        "It needs to be downloaded and extracted."
    )
    if st.button("Download and Extract"):
        try:
            os.makedirs(model_dir, exist_ok=True)
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            progress_bar = st.progress(0)
            downloaded = 0
            with open(tar_file_path, "wb") as file:
                for data in response.iter_content(1024):
                    downloaded += len(data)
                    file.write(data)
                    if total_size > 0:
                        progress_bar.progress(downloaded / total_size)

            import tarfile

            with tarfile.open(tar_file_path) as archive:
                archive.extractall(path=model_dir)
            st.success("Extraction complete!")
            return True
        except Exception as exc:
            st.markdown(f"An error occurred: {exc}")
            return False
    return True
