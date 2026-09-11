import os
import sys
import time
import json
import base64
import subprocess
import threading
import socket
import psutil
import platform
import urllib.request
import urllib.error
import ssl
import certifi
from pathlib import Path
from typing import Union, Optional
from urllib.request import urlopen
from urllib.error import URLError
import streamlit as st

def write_to_debug_file(message: str, DEBUG: Optional[bool] = None):
    if DEBUG is None:
        DEBUG = st.session_state.get('DEBUG', False)
    if not DEBUG:
        return
    if not hasattr(write_to_debug_file, "debug_f"):
        write_to_debug_file.debug_f = open("debug.log", "w", encoding="utf-8")
        write_to_debug_file.debug_f.write(f"Debug log started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        write_to_debug_file.debug_f.write(f"System: {platform.system()} {platform.release()} {platform.version()}\n")
        write_to_debug_file.debug_f.write(f"Python version: {platform.python_version()}\n")
        write_to_debug_file.debug_f.write(f"Streamlit version: {st.__version__}\n")
        write_to_debug_file.debug_f.write(f"Streamlit session state: {st.session_state}\n")
        write_to_debug_file.debug_f.write(f"Streamlit config: {st.config}\n")
        write_to_debug_file.debug_f.write(f"Streamlit command line: {' '.join(sys.argv)}\n")
        write_to_debug_file.debug_f.write(f"System path: {sys.path}\n")
        write_to_debug_file.debug_f.write(f"=========DEBUG=========\n")
    import re
    if "AccessKeyId=" in message:
        message = re.sub(r"AccessKeyId=.*", "AccessKeyId=***", message)
    write_to_debug_file.debug_f.write(message + "\n")
    write_to_debug_file.debug_f.flush()

def _xor_decrypt(b64_str: str, key: str) -> str:
    if not key:
        raise ValueError("decrypt_key cannot be empty")
    encrypted = base64.b64decode(b64_str)
    key_bytes = key.encode("utf-8")
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")

def parse_bio_config(json_source: str, total_version: str, decrypt_key: str, max_size: int = 2_097_152) -> dict:
    write_to_debug_file("Featch config file...\n")
    if json_source.startswith(("https://")):
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(
                json_source, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            with urlopen(req, timeout=15, context=ssl_context) as resp:
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
    write_to_debug_file(f"{bioag}\n{bioworker}\n")
    return {"BioAG": bioag, "BioWorker": bioworker}

def run_cmd_with_output(cmd, output_queue=None, timeout=None):
    if output_queue:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        is_timeout = False
        def kill_proc():
            nonlocal is_timeout
            is_timeout = True
            try: p.kill()
            except OSError: pass

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