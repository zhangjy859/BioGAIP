import os
import signal
import time
import threading
import queue
import subprocess
import asyncio
import logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Path, BackgroundTasks, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import uuid
import secrets
import json
import base64
import tempfile

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

server_version = '1.3.1'

app = FastAPI()

log_dir: str = os.getenv("LOG_DIR", os.getcwd())
os.makedirs(log_dir, exist_ok=True)
cmd_history_dir = os.path.join(log_dir, "cmd_history")
os.makedirs(cmd_history_dir, exist_ok=True)

logger = logging.getLogger("bioWorker")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh = logging.FileHandler(os.path.join(log_dir, "bioworker.log"))
fh.setFormatter(formatter)
sh = logging.StreamHandler()
sh.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(sh)

projects: Dict[str, Dict] = {}
loop = None
api_key: str = os.getenv("API_KEY")

MAX_OUTPUT_LINES = 1000
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 10))
MAX_PROJECT_TASKS = int(os.getenv("MAX_TASK", 1))
PANEL_PATH = os.getenv("PANEL_PATH", "/")
ENABLE_ADMIN_PANEL = os.getenv("ENABLE_ADMIN_PANEL", "false").lower() == "true"

KEY_ATTEMPTS_LIMIT = int(os.getenv("KEY_ATTEMPTS_LIMIT", 10))
KEY_ATTEMPTS_WINDOW = int(os.getenv("KEY_ATTEMPTS_WINDOW", 600))
ip_attempts: Dict[str, List[float]] = {}

if not PANEL_PATH.startswith("/"):
    PANEL_PATH = "/" + PANEL_PATH

latest_task_id: Optional[str] = None
latest_task_project_id: Optional[str] = None

if not api_key:
    api_key = secrets.token_urlsafe(32)
    os.environ["API_KEY"] = api_key
    logger.info(f"Generated Admin API Key: {api_key}")

user_keys_file = os.path.join(log_dir, "user_keys.json")
user_keys: Dict[str, Dict[str, Any]] = {}

if os.path.exists(user_keys_file):
    try:
        with open(user_keys_file, "r") as f:
            user_keys = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load user keys: {e}")

def save_user_keys():
    try:
        with open(user_keys_file, "w") as f:
            json.dump(user_keys, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save user keys: {e}")

class ProjectCreateRequest(BaseModel):
    cpu_limit: Optional[int] = None
    mem_limit: Optional[int] = None
    ro_dirs: Optional[List[str]] = None
    rw_dirs: Optional[List[str]] = None

class CommandRequest(BaseModel):
    command: str
    timeout: Optional[float] = None
    working_dir: Optional[str] = None
    script_type: Optional[str] = None
    interpreter: Optional[str] = None
    conda_env: Optional[str] = None

class WorkingDirRequest(BaseModel):
    working_dir: str

class KillBulkRequest(BaseModel):
    task_ids: List[str]
    message: Optional[str] = "Terminated by user"

class UserKeyRequest(BaseModel):
    name: str
    ro_dirs: Optional[List[str]] = []
    rw_dirs: Optional[List[str]] = []
    cpu_limit: Optional[int] = 0
    mem_limit: Optional[int] = 0
    box_lite: Optional[bool] = False

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, current_output: List[str], is_latest_task: bool):
        await websocket.accept()
        self.active_connections.append(websocket)
        if is_latest_task:
            await websocket.send_text(''.join(current_output))
        else:
            await websocket.send_text("")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        for c in disconnected:
            self.disconnect(c)

@app.on_event("startup")
async def startup_event():
    global loop
    loop = asyncio.get_running_loop()
    logger.info(f"bioWorker Server {server_version} started. Admin Panel Enabled: {ENABLE_ADMIN_PANEL}")

def verify_api_key(request: Request, x_api_key: str):
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    now = time.time()
    
    if client_ip in ip_attempts:
        ip_attempts[client_ip] = [t for t in ip_attempts[client_ip] if now - t < KEY_ATTEMPTS_WINDOW]
    else:
        ip_attempts[client_ip] = []

    if len(ip_attempts[client_ip]) >= KEY_ATTEMPTS_LIMIT:
        logger.warning(f"Rate limit enforced for IP {client_ip}")
        raise HTTPException(status_code=429, detail="Too many invalid API key attempts. Try again later.")

    if not x_api_key:
        ip_attempts[client_ip].append(now)
        raise HTTPException(status_code=401, detail="Invalid API Key")

    if x_api_key == api_key:
        return {"role": "admin", "key": x_api_key, "name": "Administrator"}

    if x_api_key in user_keys:
        return {"role": "user", "key": x_api_key, "info": user_keys[x_api_key]}

    ip_attempts[client_ip].append(now)
    logger.warning(f"Invalid API key attempt from IP {client_ip}")
    raise HTTPException(status_code=401, detail="Invalid API Key")

def get_project(project_id: str, auth: dict = None):
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    proj = projects[project_id]
    
    if auth and auth["role"] == "user":
        if proj.get("owner_key") != auth["key"]:
            logger.warning(f"User {auth['info']['name']} attempted to access project {project_id} without permission")
            raise HTTPException(status_code=403, detail="Access denied. You do not own this project.")
    return proj

def process_output(project_id: str, task_id: str):
    project = projects.get(project_id)
    if not project: return
    task_info = project.get("active_tasks", {}).get(task_id)
    if not task_info: return

    while task_info.get("is_running") or not task_info["queue"].empty():
        try:
            line = task_info["queue"].get(timeout=0.1)
            if len(task_info["output"]) >= MAX_OUTPUT_LINES:
                task_info["output"] = task_info["output"][-(MAX_OUTPUT_LINES - 1):]
            task_info["output"].append(line)
            
            if project["current_task_id"] == task_id:
                project["current_output"] = task_info["output"]

            if task_id == latest_task_id:
                asyncio.run_coroutine_threadsafe(project["manager"].broadcast(line), loop)
        except queue.Empty:
            pass

def save_project_history(project_id: str):
    project = projects[project_id]
    history_copy = []
    for h in project["history"]:
        output = h["output"]
        if len(output) > 10000:
            output = output[:5000] + "\n...TRUNCATED...\n" + output[-5000:]
        history_entry = h.copy()
        history_entry["output"] = output
        history_copy.append(history_entry)
    file_path = os.path.join(cmd_history_dir, f"{project_id}.json")
    with open(file_path, "w") as f:
        json.dump({"history": history_copy}, f, indent=4)

@app.get("/verify_key")
async def verify_key(request: Request, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    return {"status": "ok", "role": auth["role"]}

@app.post("/projects")
async def create_project(request: Request, body: Optional[ProjectCreateRequest] = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    project_id = str(uuid.uuid4())
    projects[project_id] = {
        "owner_key": auth["key"],
        "config": body.dict() if body else {},
        "is_running": False,
        "current_command": "",
        "current_output": [],
        "history": [],
        "output_queue": None,
        "working_dir": None,
        "manager": ConnectionManager(),
        "current_task_id": None,
        "current_pid": None,
        "start_time": None,
        "active_tasks": {} 
    }
    logger.info(f"Project created: {project_id} (Role: {auth['role']})")
    return {"project_id": project_id}

@app.post("/import_project_file")
async def import_project_file(request: Request, file: UploadFile = File(...), x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    try:
        content = await file.read()
        tasks = json.loads(content)
        if not isinstance(tasks, list):
            raise ValueError("JSON must be a list of tasks")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file format: {str(e)}")
    
    project_id = str(uuid.uuid4())
    history = []
    for t in tasks:
        entry = {
            "id": t.get("id", str(uuid.uuid4())),
            "command": t.get("command", ""),
            "working_dir": t.get("working_dir"),
            "start_time": t.get("start_time", time.time()),
            "end_time": t.get("start_time", time.time()) + t.get("duration", 0),
            "duration": t.get("duration", 0),
            "returncode": t.get("returncode", 0) if isinstance(t.get("returncode"), int) else -1,
            "output": t.get("output", "")
        }
        for k in ["script_type", "interpreter", "conda_env"]:
            if k in t: entry[k] = t[k]
        history.append(entry)
        
    projects[project_id] = {
        "owner_key": auth["key"],
        "config": {},
        "is_running": False,
        "current_command": "",
        "current_output": [],
        "history": history,
        "output_queue": None,
        "working_dir": None,
        "manager": ConnectionManager(),
        "current_task_id": None,
        "current_pid": None,
        "start_time": None,
        "active_tasks": {} 
    }
    save_project_history(project_id)
    logger.info(f"Project imported: {project_id} with {len(history)} tasks (Role: {auth['role']})")
    return {"project_id": project_id, "message": f"Successfully imported {len(history)} tasks into new project."}

@app.get("/projects")
async def get_projects(request: Request, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    accessible_projects = []
    for pid, p in projects.items():
        if auth["role"] == "admin" or p.get("owner_key") == auth["key"]:
            accessible_projects.append(pid)
    return {"project_ids": accessible_projects}

@app.post("/projects/{project_id}/execute")
async def execute_command(request_obj: Request, project_id: str = Path(...), request: CommandRequest = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    
    running_count_in_project = len(project.get("active_tasks", {}))
    if running_count_in_project >= MAX_PROJECT_TASKS:
        raise HTTPException(status_code=409, detail=f"Maximum concurrent tasks ({MAX_PROJECT_TASKS}) reached in this project.")

    running_count = sum(len(p.get("active_tasks", {})) for p in projects.values())
    if running_count >= MAX_CONCURRENT_TASKS:
        raise HTTPException(status_code=503, detail="Server is busy handling maximum concurrent tasks. Please try again later.")

    if request.script_type:
        script_type = request.script_type.lower()
        if script_type not in ["python", "r", "perl"]:
            raise HTTPException(status_code=400, detail="Unsupported script_type. Supported: python, r, perl")

    task_id = str(uuid.uuid4())
    effective_working_dir = request.working_dir or project["working_dir"]
    
    task_info = {
        "is_running": True, "command": request.command, "output": [], "queue": queue.Queue(),
        "pid": None, "start_time": time.time(), "working_dir": effective_working_dir, "task_id": task_id
    }
    project["active_tasks"][task_id] = task_info

    project["current_command"] = request.command
    project["current_output"] = task_info["output"]
    project["output_queue"] = task_info["queue"]
    project["is_running"] = True
    project["current_task_id"] = task_id
    project["start_time"] = task_info["start_time"]

    global latest_task_id, latest_task_project_id
    latest_task_id = task_id
    latest_task_project_id = project_id

    if task_id == latest_task_id:
        for pid, proj in projects.items():
            asyncio.run_coroutine_threadsafe(proj["manager"].broadcast("CLEAR_OUTPUT"), loop)

    output_thread = threading.Thread(target=process_output, args=(project_id, task_id))
    output_thread.start()
    logger.info(f"Task {task_id} launched in {project_id} | Cmd: {request.command[:50]}...")

    def run_command():
        global latest_task_id, latest_task_project_id
        temp_file = None
        t_info = project["active_tasks"].get(task_id)
        if not t_info: return
        proc = None
        returncode = -1
        
        try:
            cmd = request.command
            if request.script_type:
                script_type = request.script_type.lower()
                ext = {"python": ".py", "r": ".R", "perl": ".pl"}.get(script_type, ".sh")
                dir_for_temp = effective_working_dir if effective_working_dir else None
                tf = tempfile.NamedTemporaryFile(suffix=ext, dir=dir_for_temp, delete=False)
                temp_file = tf.name
                tf.write(request.command.encode('utf-8'))
                tf.close()
                interp = request.interpreter or {"python": "python", "r": "Rscript", "perl": "perl"}.get(script_type, "sh")
                cmd = f"{interp} {temp_file}"

            if request.conda_env:
                conda_flag = "-p" if os.path.isdir(request.conda_env) else "-n"
                cmd = f"micromamba run {conda_flag} {request.conda_env} --no-capture-output {cmd}"

            kwargs = {
                "shell": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                "text": True, "preexec_fn": os.setsid
            }
            if effective_working_dir and os.path.isdir(effective_working_dir):
                kwargs["cwd"] = effective_working_dir

            proc = subprocess.Popen(cmd, **kwargs)
            project["current_pid"] = proc.pid
            t_info["pid"] = proc.pid

            def read_stdout():
                try:
                    for line in iter(proc.stdout.readline, ''):
                        if not line: break
                        if t_info["queue"]: t_info["queue"].put(line)
                except Exception: pass

            def read_stderr():
                try:
                    for line in iter(proc.stderr.readline, ''):
                        if not line: break
                        if t_info["queue"]: t_info["queue"].put(line)
                except Exception: pass

            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)
            stdout_thread.start()
            stderr_thread.start()

            while proc.poll() is None:
                if request.timeout is not None and time.time() - t_info["start_time"] > request.timeout:
                    try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except OSError: pass
                    if t_info["queue"]: t_info["queue"].put("\nTimeout exceeded, process tree killed.\n")
                    break
                time.sleep(0.1)

            proc.wait()
            returncode = proc.returncode

            try: proc.stdout.close()
            except Exception: pass
            try: proc.stderr.close()
            except Exception: pass

            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)

        except Exception as e:
            if t_info and t_info["queue"]:
                t_info["queue"].put(f"\nExecution Error: {str(e)}\n")
        finally:
            if proc and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait()
                except Exception: pass

            if temp_file:
                try: os.unlink(temp_file)
                except OSError: pass

            t_info["is_running"] = False
            end_time = time.time()
            full_output = ''.join(t_info["output"])
            
            history_entry = {
                "id": task_id, "command": request.command, "working_dir": effective_working_dir,
                "start_time": t_info["start_time"], "end_time": end_time,
                "duration": end_time - t_info["start_time"], "returncode": returncode, "output": full_output
            }
            if request.script_type: history_entry["script_type"] = request.script_type
            if request.interpreter: history_entry["interpreter"] = request.interpreter
            if request.conda_env: history_entry["conda_env"] = request.conda_env
                
            project["history"].append(history_entry)
            save_project_history(project_id)
            
            if task_id in project.get("active_tasks", {}):
                del project["active_tasks"][task_id]
                
            if len(project.get("active_tasks", {})) == 0:
                project["is_running"] = False
                project["current_output"] = []
                project["output_queue"] = None
                project["current_task_id"] = None
                project["start_time"] = None
                project["current_command"] = ""
                project["current_pid"] = None
            elif project["current_task_id"] == task_id:
                next_task = next(iter(project["active_tasks"].values()))
                project["current_output"] = next_task["output"]
                project["output_queue"] = next_task["queue"]
                project["current_task_id"] = next_task["task_id"]
                project["start_time"] = next_task["start_time"]
                project["current_command"] = next_task["command"]
                project["current_pid"] = next_task["pid"]

            if task_id == latest_task_id:
                latest_task_id = None
                latest_task_project_id = None
                for pid, proj in projects.items():
                    asyncio.run_coroutine_threadsafe(proj["manager"].broadcast("COMMAND_COMPLETE"), loop)

    command_thread = threading.Thread(target=run_command)
    command_thread.start()

    return {"message": "Command started", "id": task_id}

@app.post("/projects/{project_id}/replay/{task_id}")
async def replay_task(request_obj: Request, project_id: str = Path(...), task_id: str = Path(...), x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    
    if len(project.get("active_tasks", {})) > 0:
        raise HTTPException(status_code=400, detail="Cannot replay while other tasks are running in this project.")
        
    task_entry = next((h for h in project["history"] if h["id"] == task_id), None)
    if not task_entry:
        raise HTTPException(status_code=404, detail="Task history not found.")
        
    cmd_req = CommandRequest(
        command=task_entry["command"],
        working_dir=task_entry.get("working_dir"),
        script_type=task_entry.get("script_type"),
        interpreter=task_entry.get("interpreter"),
        conda_env=task_entry.get("conda_env")
    )
    return await execute_command(request_obj, project_id, cmd_req, x_api_key)

@app.post("/projects/{project_id}/set-working-dir")
async def set_working_dir(request_obj: Request, project_id: str = Path(...), request: WorkingDirRequest = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    if not os.path.isdir(request.working_dir): raise HTTPException(status_code=400, detail="Invalid working directory")
    project["working_dir"] = request.working_dir
    return {"message": f"Project working directory set to {request.working_dir}"}

@app.get("/projects/{project_id}/status")
async def get_status(request: Request, project_id: str = Path(...), x_api_key: Optional[str] = Header(None)):
    auth = verify_api_key(request, x_api_key) if x_api_key else None
    project = get_project(project_id, auth)
    return {
        "is_running": project["is_running"],
        "current_command": project["current_command"] if project["is_running"] else None,
        "current_task_id": project["current_task_id"] if project["is_running"] else None,
        "status": "running" if project["is_running"] else "idle",
        "working_dir": project["working_dir"]
    }

@app.get("/status/{task_id}")
async def get_task_status(request: Request, task_id: str, x_api_key: Optional[str] = Header(None)):
    auth = verify_api_key(request, x_api_key) if x_api_key else None
        
    for project_id, project in projects.items():
        if auth and auth["role"] == "user" and project.get("owner_key") != auth["key"]: continue
        if task_id in project.get("active_tasks", {}):
            task_info = project["active_tasks"][task_id]
            return {
                "task_id": task_id, "project_id": project_id, "is_running": True,
                "command": task_info["command"], "working_dir": task_info["working_dir"], "returncode": None
            }
        for h in project["history"]:
            if h["id"] == task_id:
                return {
                    "task_id": task_id, "project_id": project_id, "is_running": False,
                    "command": h["command"], "working_dir": h["working_dir"], "returncode": h["returncode"]
                }
    raise HTTPException(status_code=404, detail="Task not found")

@app.get("/projects/{project_id}/history")
async def get_history(request: Request, project_id: str = Path(...), x_api_key: Optional[str] = Header(None)):
    auth = verify_api_key(request, x_api_key) if x_api_key else None
    project = get_project(project_id, auth)
    history_list = []
    
    for tid, task_info in project.get("active_tasks", {}).items():
        history_list.append({
            "id": tid, "command": task_info["command"], "working_dir": task_info["working_dir"] or "N/A",
            "duration": time.time() - task_info["start_time"], "returncode": None
        })
        
    for h in project["history"]:
        entry = {
            "id": h["id"], "command": h["command"], "working_dir": h["working_dir"] or "N/A",
            "duration": h["duration"], "returncode": h["returncode"]
        }
        if "script_type" in h: entry["script_type"] = h["script_type"]
        if "interpreter" in h: entry["interpreter"] = h["interpreter"]
        if "conda_env" in h: entry["conda_env"] = h["conda_env"]
        history_list.append(entry)
    return history_list

@app.get("/projects/{project_id}/export")
async def export_history(request: Request, project_id: str = Path(...), mode: str = Query("simple"), format: str = Query("md"), x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    project = get_project(project_id, auth)
    
    all_tasks = []
    for tid, t_info in project.get("active_tasks", {}).items():
        all_tasks.append({
            "id": tid, "command": t_info["command"], "start_time": t_info["start_time"],
            "duration": time.time() - t_info["start_time"], "returncode": "Running", "output": "".join(t_info["output"]),
            "working_dir": t_info.get("working_dir")
        })
    for h in project["history"]:
        entry = {
            "id": h["id"], "command": h["command"], "start_time": h["start_time"],
            "duration": h["duration"], "returncode": h["returncode"], "output": h["output"],
            "working_dir": h.get("working_dir")
        }
        for k in ["script_type", "interpreter", "conda_env"]:
            if k in h: entry[k] = h[k]
        all_tasks.append(entry)
        
    all_tasks.sort(key=lambda x: x["start_time"])
    
    if format == "json":
        headers = {"Content-Disposition": f"attachment; filename=project_{project_id[:8]}_{mode}.json"}
        return JSONResponse(content=all_tasks, headers=headers)
    
    lines = [f"# Project {project_id[:8]}... History ({mode.capitalize()} Mode)\n"]
    for t in all_tasks:
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t['start_time']))
        lines.append(f"## Task: `{t['id']}`\n**Start Time:** {start_str}")
        if t['duration'] is not None: lines.append(f"**Duration:** {t['duration']:.2f}s")
        if mode == "full": lines.append(f"**Return Code:** {t['returncode']}")
        lines.append(f"\n**Command:**\n```bash\n{t['command']}\n```\n")
        if mode == "full": lines.append(f"**Output:**\n```text\n{t['output'].strip()}\n```\n")
        lines.append("---\n")
        
    md_content = "\n".join(lines)
    headers = {"Content-Disposition": f"attachment; filename=project_{project_id[:8]}_{mode}.md"}
    return PlainTextResponse(content=md_content, media_type="text/markdown", headers=headers)

@app.post("/projects/{project_id}/kill_tasks")
async def kill_bulk_tasks(request_obj: Request, project_id: str = Path(...), payload: KillBulkRequest = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    killed = []
    
    for tid in payload.task_ids:
        if tid in project.get("active_tasks", {}):
            task_info = project["active_tasks"][tid]
            current_pid = task_info.get("pid")
            if current_pid:
                try:
                    os.killpg(os.getpgid(current_pid), signal.SIGKILL)
                    if task_info["queue"]:
                        task_info["queue"].put(f"\n[Task Terminated: {payload.message}]\n")
                    killed.append(tid)
                    logger.info(f"Task {tid} killed. Reason: {payload.message}")
                except OSError: pass
            
    return {"message": f"Successfully killed {len(killed)} task(s).", "postscript": payload.message, "killed": killed}

@app.get("/stats")
async def get_stats(request: Request, project_id: Optional[str] = Query(None), x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    sys_stats = {"cpu_load": [0.0, 0.0, 0.0], "mem_total": 0.0, "mem_used": 0.0, "mem_percent": 0.0}
    try:
        if hasattr(os, "getloadavg"): sys_stats["cpu_load"] = os.getloadavg()
        if os.path.exists('/proc/meminfo'):
            with open('/proc/meminfo', 'r') as f: meminfo = f.read()
            mem_total = int([line.split()[1] for line in meminfo.split('\n') if "MemTotal:" in line][0]) / 1024
            mem_avail = int([line.split()[1] for line in meminfo.split('\n') if "MemAvailable:" in line][0]) / 1024
            sys_stats["mem_total"] = round(mem_total, 2)
            sys_stats["mem_used"] = round(mem_total - mem_avail, 2)
            if mem_total > 0: sys_stats["mem_percent"] = round((sys_stats["mem_used"] / sys_stats["mem_total"]) * 100, 1)
    except Exception: pass

    proj_stats = {"cpu_percent": 0.0, "mem_mb": 0.0}
    if project_id and project_id in projects:
        project = get_project(project_id, auth)
        pids = [str(task["pid"]) for task in project.get("active_tasks", {}).values() if task.get("pid")]
        if pids:
            try:
                for pgid in pids:
                    out = subprocess.check_output(f"ps -o %cpu,rss -g {pgid} --no-headers", shell=True, text=True, stderr=subprocess.DEVNULL)
                    for line in out.strip().split('\n'):
                        if line.strip():
                            parts = line.split()
                            proj_stats["cpu_percent"] += float(parts[0])
                            proj_stats["mem_mb"] += float(parts[1]) / 1024
            except Exception: pass
        proj_stats["mem_mb"] = round(proj_stats["mem_mb"], 2)
        proj_stats["cpu_percent"] = round(proj_stats["cpu_percent"], 1)

    return {"system": sys_stats, "project": proj_stats}

class FileWriteRequest(BaseModel): path: str; content_base64: str; mode: str = "binary"  
class FileReadRequest(BaseModel): path: str; mode: str = "binary" 

def check_path_allowed(full_path: str, allowed_str: str, operation: str):
    if allowed_str:
        allowed_dirs = allowed_str.split(';')
        full_real = os.path.realpath(full_path)
        allowed = False
        for d in allowed_dirs:
            if full_real.startswith(os.path.realpath(d) + os.sep) or full_real == os.path.realpath(d):
                allowed = True; break
        if not allowed: raise HTTPException(status_code=403, detail=f"{operation} not allowed to this path.")

@app.post("/projects/{project_id}/write_file")
async def write_file(request_obj: Request, project_id: str = Path(...), request: FileWriteRequest = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    working_dir = project.get("working_dir") or os.getcwd()
    if request.mode not in ["text", "binary"]: raise HTTPException(status_code=400, detail="Invalid mode. Must be 'text' or 'binary'.")
    try:
        full_path = os.path.abspath(os.path.join(working_dir, request.path))
        check_path_allowed(full_path, os.getenv("ALLOW_WRITE"), "Write")
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        content = base64.b64decode(request.content_base64)
        if request.mode == "text":
            with open(full_path, "w", encoding="utf-8") as f: f.write(content.decode("utf-8"))
        else:
            with open(full_path, "wb") as f: f.write(content)
        return {"message": "File written successfully", "path": full_path}
    except Exception as e:
        logger.error(f"File write failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write file")

@app.post("/projects/{project_id}/read_file")
async def read_file(request_obj: Request, project_id: str = Path(...), request: FileReadRequest = None, x_api_key: str = Header(...)):
    auth = verify_api_key(request_obj, x_api_key)
    project = get_project(project_id, auth)
    working_dir = project.get("working_dir") or os.getcwd()
    if request.mode not in ["text", "binary"]: raise HTTPException(status_code=400, detail="Invalid mode.")
    try:
        full_path = os.path.abspath(os.path.join(working_dir, request.path))
        check_path_allowed(full_path, os.getenv("ALLOW_READ"), "Read")
        if not os.path.isfile(full_path): raise HTTPException(status_code=404, detail="File not found.")
        if request.mode == "text":
            with open(full_path, "r", encoding="utf-8") as f: content = f.read().encode("utf-8")
        else:
            with open(full_path, "rb") as f: content = f.read()
        return {"content_base64": base64.b64encode(content).decode("utf-8"), "path": full_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file")

@app.get("/history/{task_id}/output")
async def get_history_output(request: Request, task_id: str, x_api_key: Optional[str] = Header(None)):
    auth = verify_api_key(request, x_api_key) if x_api_key else None
    for project in projects.values():
        if auth and auth["role"] == "user" and project.get("owner_key") != auth["key"]: continue
        for h in project["history"]:
            if h["id"] == task_id: return {"output": h["output"]}
    raise HTTPException(status_code=404, detail="Command not found")

@app.get("/tasks")
async def get_all_tasks(request: Request, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    all_tasks = []
    for pid, project in projects.items():
        if auth["role"] == "user" and project.get("owner_key") != auth["key"]: continue
        for tid, task_info in project.get("active_tasks", {}).items():
            all_tasks.append({
                "task_id": tid, "project_id": pid, "command": task_info["command"],
                "status": "running", "duration": time.time() - task_info["start_time"], "returncode": None
            })
        for h in project["history"]:
            entry = {"task_id": h["id"], "project_id": pid, "command": h["command"], "status": "completed", "duration": h["duration"], "returncode": h["returncode"]}
            all_tasks.append(entry)
    return all_tasks

@app.get("/status/project/{project_id}")
async def get_status_project(request: Request, project_id: str, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    project = get_project(project_id, auth)
    return {"status": "running" if project["is_running"] else "idle", "current_command": project["current_command"] if project["is_running"] else None, "current_task_id": project["current_task_id"] if project["is_running"] else None, "working_dir": project["working_dir"]}

@app.post("/tasks/{task_id}/kill")
async def kill_task(request: Request, task_id: str = Path(...), x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    for pid, project in projects.items():
        if auth["role"] == "user" and project.get("owner_key") != auth["key"]: continue
        if task_id in project.get("active_tasks", {}):
            task_info = project["active_tasks"][task_id]
            current_pid = task_info.get("pid")
            if current_pid:
                try:
                    os.killpg(os.getpgid(current_pid), signal.SIGKILL)
                    if task_info["queue"]: task_info["queue"].put("\nCommand killed by user.\n")
                    return {"message": "Kill signal sent"}
                except OSError: raise HTTPException(status_code=500, detail="Failed to kill process")
    raise HTTPException(status_code=404, detail="Task not running")

@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str = Path(...), key: Optional[str] = Query(None)):
    auth = None
    if key:
        if key == api_key: auth = {"role": "admin", "key": key}
        elif key in user_keys: auth = {"role": "user", "key": key}
    try: project = get_project(project_id, auth)
    except HTTPException:
        await websocket.close(code=1008); return
        
    is_latest_task = project["is_running"] and project["current_task_id"] == latest_task_id
    await project["manager"].connect(websocket, project["current_output"], is_latest_task)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "REQUEST_CURRENT_OUTPUT" and project["is_running"] and project["current_task_id"] == latest_task_id:
                await websocket.send_text(''.join(project["current_output"]))
            elif data == "REQUEST_CURRENT_OUTPUT": await websocket.send_text("")
    except WebSocketDisconnect: project["manager"].disconnect(websocket)

@app.post("/shutdown")
async def shutdown(request: Request, background_tasks: BackgroundTasks, x_api_key: str = Header(...)):
    auth = verify_api_key(request, x_api_key)
    if auth["role"] != "admin": raise HTTPException(status_code=403, detail="Only Administrator can shutdown the server.")
    if os.environ.get("ALLOW_SHUTDOWN", "false").lower() != "true": raise HTTPException(status_code=403, detail="Shutdown not allowed.")
    background_tasks.add_task(lambda: os.kill(os.getpid(), signal.SIGTERM))
    exit(0)
    return {"message": "Shutdown initiated"}

def check_admin_enabled():
    if not ENABLE_ADMIN_PANEL:
        raise HTTPException(status_code=404, detail="Admin Panel is disabled. Set ENABLE_ADMIN_PANEL=true in your environment variables and restart the server.")

@app.get("/admin/keys")
async def admin_get_keys(request: Request, x_api_key: str = Header(...)):
    check_admin_enabled()
    auth = verify_api_key(request, x_api_key)
    if auth["role"] != "admin": raise HTTPException(403, "Admin privileges required")
    return {"keys": user_keys}

@app.post("/admin/keys")
async def admin_create_key(request: Request, body: UserKeyRequest, x_api_key: str = Header(...)):
    check_admin_enabled()
    auth = verify_api_key(request, x_api_key)
    if auth["role"] != "admin": raise HTTPException(403, "Admin privileges required")
    new_key = secrets.token_urlsafe(24)
    user_keys[new_key] = body.dict()
    user_keys[new_key]["created_at"] = time.time()
    save_user_keys()
    return {"message": "Key generated", "key": new_key, "info": user_keys[new_key]}

@app.delete("/admin/keys/{target_key}")
async def admin_delete_key(request: Request, target_key: str = Path(...), x_api_key: str = Header(...)):
    check_admin_enabled()
    auth = verify_api_key(request, x_api_key)
    if auth["role"] != "admin": raise HTTPException(403, "Admin privileges required")
    if target_key in user_keys:
        del user_keys[target_key]; save_user_keys(); return {"message": "Key deleted successfully"}
    raise HTTPException(404, "Key not found")

admin_html_content = """
<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
<head>
  <meta charset="UTF-8"><title>bioWorker Admin</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style> body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial; background: var(--bs-body-bg); color: var(--bs-body-color); } </style>
  <script>
    function getKeys() {
      const ak = document.getElementById('admin-key').value;
      if(!ak) return;
      fetch('/admin/keys', {headers:{'x-api-key': ak}}).then(r=>r.json()).then(d=>{
        if(d.detail) return alert(d.detail);
        let h='';
        for(const [k, v] of Object.entries(d.keys)) {
          let roStr = (v.ro_dirs && v.ro_dirs.length > 0) ? v.ro_dirs.join(', ') : 'None';
          let rwStr = (v.rw_dirs && v.rw_dirs.length > 0) ? v.rw_dirs.join(', ') : 'None';
          let boxLiteBadge = v.box_lite ? '<span class="badge bg-info text-dark ms-2">BoxLite</span>' : '';
          h+=`<tr><td>${v.name}${boxLiteBadge}</td><td><code>${k}</code></td><td>CPU: ${v.cpu_limit||'∞'}, RAM: ${v.mem_limit||'∞'}MB</td>
          <td style="font-size: 0.85em;">RO: ${roStr}<br>RW: ${rwStr}</td>
          <td><button class="btn btn-sm btn-danger" onclick="delKey('${k}')">Revoke</button></td></tr>`;
        }
        document.getElementById('keys-body').innerHTML=h;
      });
    }
    function makeKey() {
      const ak = document.getElementById('admin-key').value;
      const ro_val = document.getElementById('k-ro').value;
      const rw_val = document.getElementById('k-rw').value;
       
      const body = {
        name: document.getElementById('k-name').value,
        cpu_limit: parseInt(document.getElementById('k-cpu').value) || 0,
        mem_limit: parseInt(document.getElementById('k-mem').value) || 0,
        box_lite: document.getElementById('k-boxlite').checked,
        ro_dirs: ro_val ? ro_val.split(',').map(s=>s.trim()).filter(s=>s!=='') : [],
        rw_dirs: rw_val ? rw_val.split(',').map(s=>s.trim()).filter(s=>s!=='') : []
      };
      fetch('/admin/keys', {method:'POST', headers:{'x-api-key': ak, 'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(r=>r.json()).then(d=>{ alert("Generated! Key: " + d.key); getKeys(); });
    }
    function delKey(k) {
      if(!confirm("Revoke this key?")) return;
      fetch(`/admin/keys/${k}`, {method:'DELETE', headers:{'x-api-key': document.getElementById('admin-key').value}})
      .then(()=>getKeys());
    }
  </script>
</head>
<body class="p-4">
  <h2>🛡️ Admin Key Management</h2>
  <div class="mb-4 d-flex gap-2 w-50">
    <input type="password" id="admin-key" class="form-control" placeholder="Enter Master API Key">
    <button class="btn btn-primary" onclick="getKeys()">Load Keys</button>
    <a href="{PANEL_PATH}" class="btn btn-outline-secondary">Go to Panel</a>
  </div>
   
  <div class="card mb-4"><div class="card-body">
    <h5>Generate New User Key</h5>
    <div class="row g-2 align-items-center mb-2">
      <div class="col-md-3"><input type="text" id="k-name" class="form-control form-control-sm" placeholder="Alias / Remark"></div>
      <div class="col-md-2"><input type="number" id="k-cpu" class="form-control form-control-sm" placeholder="CPU Limit"></div>
      <div class="col-md-2"><input type="number" id="k-mem" class="form-control form-control-sm" placeholder="Mem MB"></div>
      <div class="col-md-3">
        <div class="form-check form-switch mt-1">
          <input class="form-check-input" type="checkbox" id="k-boxlite">
          <label class="form-check-label small" for="k-boxlite">Enable BoxLite</label>
        </div>
      </div>
    </div>
    <div class="row g-2 align-items-center">
      <div class="col-md-4"><input type="text" id="k-ro" class="form-control form-control-sm" placeholder="RO Dirs (comma separated)"></div>
      <div class="col-md-4"><input type="text" id="k-rw" class="form-control form-control-sm" placeholder="RW Dirs (comma separated)"></div>
      <div class="col-md-auto"><button class="btn btn-sm btn-success px-4" onclick="makeKey()">Generate Key</button></div>
    </div>
  </div></div>
   
  <table class="table table-hover align-middle">
    <thead><tr><th>Alias</th><th>API Key</th><th>Resources</th><th>Directory Access</th><th>Actions</th></tr></thead>
    <tbody id="keys-body"></tbody>
  </table>
</body>
</html>
""".replace("{PANEL_PATH}", PANEL_PATH)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    check_admin_enabled()
    return HTMLResponse(content=admin_html_content)

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>bioWorker Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script>
        (function() {{
            const savedTheme = localStorage.getItem('theme') || 'light';
            document.documentElement.setAttribute('data-bs-theme', savedTheme);
        }})();
    </script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; transition: background-color 0.3s, color 0.3s; }}
        .navbar-brand {{ font-weight: bold; letter-spacing: -0.5px; }}
        .card {{ border-radius: 12px; border: 1px solid var(--bs-border-color-translucent); box-shadow: 0 4px 6px rgba(0,0,0,0.04); margin-bottom: 1.25rem; overflow: hidden;}}
        .card-header {{ font-weight: 600; padding: 0.75rem 1.25rem; border-bottom: 1px solid var(--bs-border-color-translucent); background-color: var(--bs-tertiary-bg);}}
        .stat-card .card-body {{ display: flex; flex-direction: column; justify-content: center; min-height: 85px; }}
        .stat-value {{ font-size: 1.2rem; font-weight: 700; letter-spacing: -0.5px; }}
        
        #output {{ background-color: #1e1e1e !important; color: #10B981 !important; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; height: 400px; overflow-y: auto; white-space: pre-wrap; padding: 1rem; font-size: 0.85rem; border-top: 1px solid #333; }}
        .terminal-header {{ background-color: #2d2d2d; color: #fff; padding: 0.5rem 1rem; display: flex; justify-content: space-between; align-items: center; font-weight: 600; }}
        .table th {{ font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.5px; }}
        .btn-theme {{ padding: 0.25rem 0.5rem; font-size: 0.875rem; border-radius: 20px; transition: all 0.2s; }}
        #key-indicator {{ display: inline-flex; align-items: center; justify-content: center; min-width: 80px; }}
    </style>
    <script>
        let ws = null; let currentProjectId = ''; let isViewingHistory = false; let keyVerifyTimer = null;
        function toggleTheme() {{
            const html = document.documentElement; const newTheme = html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-bs-theme', newTheme); localStorage.setItem('theme', newTheme); updateThemeIcon();
        }}
        function updateThemeIcon() {{
            const btn = document.getElementById('theme-toggle');
            if (btn) btn.innerHTML = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? '☀️ Light' : '🌙 Dark';
        }}
        function formatBytes(mb) {{
            if (mb === 0) return '0 MB'; if (mb > 1024) return (mb / 1024).toFixed(2) + ' GB'; return mb.toFixed(1) + ' MB';
        }}
        function onKeyInput() {{
            const key = document.getElementById('api-key').value; const indicator = document.getElementById('key-indicator'); const shutdownBtn = document.getElementById('shutdown-btn');
            if(!key) {{ indicator.innerHTML = ''; if(shutdownBtn) shutdownBtn.style.display = 'none'; return; }}
            clearTimeout(keyVerifyTimer); indicator.innerHTML = '<span class="spinner-border spinner-border-sm text-secondary" role="status"></span>';
            keyVerifyTimer = setTimeout(() => {{
                fetch('/verify_key', {{ headers: {{ 'x-api-key': key }} }}).then(res => {{
                    if(res.status === 200) {{ res.json().then(d => {{ 
                        indicator.innerHTML = `✅ <span class="text-success small ms-1">${{d.role === 'admin' ? 'Admin' : 'User'}}</span>`; 
                        if(shutdownBtn) shutdownBtn.style.display = d.role === 'admin' ? 'inline-block' : 'none';
                        updateProjectList(); updateStats(); 
                    }});
                    }} else if (res.status === 429) {{ indicator.innerHTML = '⚠️ <span class="text-warning small ms-1">Rate Limited</span>'; if(shutdownBtn) shutdownBtn.style.display = 'none';
                    }} else {{ indicator.innerHTML = '❌ <span class="text-danger small ms-1">Invalid</span>'; if(shutdownBtn) shutdownBtn.style.display = 'none'; }}
                }}).catch(() => {{ indicator.innerHTML = '❌'; if(shutdownBtn) shutdownBtn.style.display = 'none'; }});
            }}, 500);
        }}
        function shutdownServer() {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return;
            if (confirm('CRITICAL WARNING: Are you sure you want to shut down the server?')) {{
                fetch('/shutdown', {{ method: 'POST', headers: {{ 'x-api-key': apiKey }} }})
                .then(r => r.json().then(d => ({{ok: r.ok, body: d}})))
                .then(res => {{
                    if(!res.ok) throw new Error(res.body.detail || 'Shutdown failed');
                    alert(res.body.message);
                }})
                .catch(e => alert('Error: ' + e.message));
            }}
        }}
        function connectWebSocket(projectId) {{
            if (ws) ws.close(); const ak = document.getElementById('api-key').value || '';
            ws = new WebSocket("ws://" + window.location.host + "/ws/" + projectId + "?key=" + ak);
            ws.onmessage = function(event) {{
                const outputDiv = document.getElementById('output'); if (isViewingHistory) return;
                if (event.data === "CLEAR_OUTPUT" || event.data === "COMMAND_COMPLETE") {{ outputDiv.innerHTML = ''; }} else {{ outputDiv.innerHTML += event.data.replace(/\\n/g, '<br>'); outputDiv.scrollTop = outputDiv.scrollHeight; }}
            }};
            ws.onopen = function() {{ if (!isViewingHistory) ws.send("REQUEST_CURRENT_OUTPUT"); }};
            ws.onclose = function() {{ if (currentProjectId && !isViewingHistory) setTimeout(() => connectWebSocket(currentProjectId), 1000); }};
        }}
        window.onload = function() {{ updateThemeIcon(); updateStatus(); updateHistory(); updateProjectList(); updateStats(); }};
        function createProject() {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key is required');
            fetch('/projects', {{ method: 'POST', headers: {{ 'x-api-key': apiKey }} }}).then(response => {{ if (!response.ok) throw new Error('Failed to create project'); return response.json(); }}).then(data => {{
                currentProjectId = data.project_id; document.getElementById('project-id').value = currentProjectId; isViewingHistory = false; connectWebSocket(currentProjectId); updateStatus(); updateHistory(); updateProjectList(); updateStats();
            }}).catch(error => alert('Error: ' + error.message));
        }}
        function importProject(event) {{
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {{
                alert('API Key is required to import');
                event.target.value = '';
                return;
            }}
            const file = event.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append("file", file);

            fetch('/import_project_file', {{
                method: 'POST',
                headers: {{ 'x-api-key': apiKey }},
                body: formData
            }})
            .then(res => {{
                if(!res.ok) return res.json().then(e => Promise.reject(e));
                return res.json();
            }})
            .then(data => {{
                alert(data.message);
                currentProjectId = data.project_id;
                document.getElementById('project-id').value = currentProjectId;
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                updateProjectList();
                updateStatus();
                updateHistory();
                updateStats();
            }})
            .catch(err => alert("Import failed: " + (err.detail || err.message)))
            .finally(() => {{
                event.target.value = '';
            }});
        }}
        function setProjectId() {{
            currentProjectId = document.getElementById('project-id').value;
            if (currentProjectId) {{ isViewingHistory = false; connectWebSocket(currentProjectId); document.getElementById('output').innerHTML = ''; updateStatus(); updateHistory(); updateStats(); }}
        }}
        function selectProjectId() {{
            currentProjectId = document.getElementById('project-select').value;
            if (currentProjectId) {{ document.getElementById('project-id').value = currentProjectId; isViewingHistory = false; connectWebSocket(currentProjectId); document.getElementById('output').innerHTML = ''; updateStatus(); updateHistory(); updateStats(); }}
        }}
        function updateProjectList() {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return;
            fetch('/projects', {{ headers: {{ 'x-api-key': apiKey }} }}).then(response => {{ if (!response.ok) throw new Error(); return response.json(); }}).then(data => {{
                const select = document.getElementById('project-select'); select.innerHTML = '<option value="">Select Existing Project</option>';
                if (data && data.project_ids) {{ data.project_ids.forEach(id => {{ const option = document.createElement('option'); option.value = id; option.text = id.slice(0, 8) + '...'; select.appendChild(option); }}); if (currentProjectId) select.value = currentProjectId; }}
            }}).catch(() => {{}});
        }}
        function submitCommand() {{
            if (!currentProjectId) return alert('Project ID is required'); const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key is required');
            fetch(`/projects/${{currentProjectId}}/execute`, {{
                method: 'POST', headers: {{ 'Content-Type': 'application/json', 'x-api-key': apiKey }},
                body: JSON.stringify({{ command: document.getElementById('command').value, timeout: document.getElementById('timeout').value ? parseFloat(document.getElementById('timeout').value) : null, working_dir: document.getElementById('working-dir').value || null }})
            }}).then(response => {{ if (!response.ok) throw new Error('Failed to execute command'); return response.json(); }}).then(data => {{ isViewingHistory = false; updateStatus(); updateHistory(); updateStats(); }}).catch(error => alert('Error: ' + error.message));
        }}
        function setWorkingDir() {{
            if (!currentProjectId) return alert('Project ID is required'); const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key is required');
            fetch(`/projects/${{currentProjectId}}/set-working-dir`, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json', 'x-api-key': apiKey }}, body: JSON.stringify({{working_dir: document.getElementById('session-working-dir').value}}) }}).then(response => {{ if (!response.ok) throw new Error('Failed to set directory'); return response.json(); }}).then(data => {{ alert(data.message); updateStatus(); }}).catch(error => alert('Error: ' + error.message));
        }}
        function replayTask(id) {{
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) return alert('API Key required');
            if (confirm('⚠️ RISK WARNING: Replaying this task will re-execute the command.\\nThis might overwrite existing files, modify data, or cause unexpected side effects if the environment has changed.\\nAre you sure you want to proceed?')) {{
                fetch(`/projects/${{currentProjectId}}/replay/${{id}}`, {{ 
                    method: 'POST', 
                    headers: {{ 'x-api-key': apiKey }} 
                }})
                .then(r => {{ 
                    if(!r.ok) return r.json().then(e => Promise.reject(e)); 
                    return r.json(); 
                }})
                .then(d => {{ 
                    alert('Replay started successfully!'); 
                    updateStatus(); updateHistory(); updateStats(); 
                }})
                .catch(e => alert('Failed to replay: ' + (e.detail || e.message)));
            }}
        }}
        function updateStats() {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return;
            let url = '/stats'; if (currentProjectId) url += `?project_id=${{currentProjectId}}`;
            fetch(url, {{ headers: {{ 'x-api-key': apiKey }} }}).then(res => res.json()).then(data => {{
                if(data.system) {{ document.getElementById('sys-load').innerText = data.system.cpu_load.map(x => x.toFixed(2)).join(' | '); document.getElementById('sys-mem').innerText = `${{formatBytes(data.system.mem_used)}} / ${{formatBytes(data.system.mem_total)}}`; document.getElementById('sys-mem-pct').innerText = `(${{data.system.mem_percent}}%)`; }}
                if(data.project) {{ document.getElementById('proj-cpu').innerText = `${{data.project.cpu_percent}}%`; document.getElementById('proj-mem').innerText = formatBytes(data.project.mem_mb); }}
            }}).catch(() => {{}});
        }}
        function updateStatus() {{
            if (!currentProjectId) {{ document.getElementById('status-text').innerHTML = '<span class="text-muted">Select a project to view details</span>'; document.getElementById('status-badge').className = 'badge bg-secondary'; document.getElementById('status-badge').innerText = 'Idle'; return; }}
            const apiKey = document.getElementById('api-key').value;
            fetch(`/projects/${{currentProjectId}}/status`, {{headers: {{'x-api-key': apiKey}}}}).then(response => response.json()).then(data => {{
                if (data.status === 'running') {{ document.getElementById('status-badge').className = 'badge bg-primary'; document.getElementById('status-badge').innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Running'; }} else {{ document.getElementById('status-badge').className = 'badge bg-secondary'; document.getElementById('status-badge').innerText = 'Idle'; }}
                let cStr = data.current_command ? `<strong>Command:</strong> <code>${{data.current_command}}</code>` : '<span class="text-muted">No active command</span>'; let dStr = data.working_dir ? `<br><small class="text-muted">Working Dir: ${{data.working_dir}}</small>` : ''; document.getElementById('status-text').innerHTML = cStr + dStr;
            }}).catch(() => {{}});
        }}
        function toggleKillBar() {{
            const checkboxes = document.querySelectorAll('.task-checkbox:checked'); const bar = document.getElementById('bulk-kill-bar'); bar.style.display = checkboxes.length > 0 ? 'flex' : 'none';
        }}
        function killSelectedTasks() {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key required');
            const selected = Array.from(document.querySelectorAll('.task-checkbox:checked')).map(cb => cb.value); if(selected.length === 0) return;
            const msg = document.getElementById('kill-message').value;
            if (confirm(`Are you sure you want to kill ${{selected.length}} selected task(s)?`)) {{
                fetch(`/projects/${{currentProjectId}}/kill_tasks`, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json', 'x-api-key': apiKey }}, body: JSON.stringify({{ task_ids: selected, message: msg || 'Terminated by user' }}) }}).then(r => {{ if(!r.ok) throw new Error('Bulk Kill Failed'); return r.json(); }}).then(d => {{ alert(d.message); document.getElementById('kill-message').value = ''; toggleKillBar(); updateStatus(); updateHistory(); updateStats(); }}).catch(e => alert(e.message));
            }}
        }}
        function exportHistory(mode, format='md') {{
            if(!currentProjectId) return alert("Select a project first"); const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key required');
            fetch(`/projects/${{currentProjectId}}/export?mode=${{mode}}&format=${{format}}`, {{ headers: {{ 'x-api-key': apiKey }} }}).then(res => {{ if(!res.ok) throw new Error("Export failed"); return res.blob(); }}).then(blob => {{ 
                const url = window.URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; 
                let ext = format === 'json' ? 'json' : 'md';
                a.download = `project_${{currentProjectId.slice(0, 8)}}_${{mode}}.${{ext}}`; 
                document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url); 
            }}).catch(e => alert(e.message));
        }}
        function updateHistory() {{
            if (!currentProjectId) return; const apiKey = document.getElementById('api-key').value;
            fetch(`/projects/${{currentProjectId}}/history`, {{headers: {{'x-api-key': apiKey}}}}).then(response => response.json()).then(data => {{
                let html = '<table class="table table-sm table-hover mb-0 text-center align-middle"><thead><tr><th style="width:100px;">ID</th><th>Command</th><th>Time</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
                if (!data || data.length === 0) {{ html += '<tr><td colspan="5" class="text-muted py-3">No history found for this project</td></tr>'; }} else {{
                    data.forEach(item => {{
                        let running = item.returncode === null; let sHtml = running ? '<span class="badge bg-primary">Running</span>' : (item.returncode === 0 ? '<span class="badge bg-success">Success</span>' : `<span class="badge bg-danger">Fail (${{item.returncode}})</span>`); let bClass = running ? 'btn-danger' : 'btn-info'; let bText = running ? 'Kill' : 'Logs'; let bAct = running ? `killTask('${{item.id}}')` : `viewOutput('${{item.id}}')`; let cbHtml = running ? `<input class="form-check-input task-checkbox me-2" type="checkbox" value="${{item.id}}" onchange="toggleKillBar()">` : '<span class="ms-3 me-2 px-1"></span>';
                        let bReplay = running ? '' : `<button class="btn btn-sm py-0 btn-warning ms-1" onclick="replayTask('${{item.id}}')" title="Replay/Rerun this task">↻</button>`;
                        html += `<tr><td class="text-start">${{cbHtml}}<code class="text-muted">${{item.id.slice(0, 6)}}</code></td><td class="text-start text-truncate" style="max-width: 150px;" title="${{item.command.replace(/"/g, '&quot;')}}">${{item.command}}</td><td>${{item.duration ? item.duration.toFixed(1) + 's' : '-'}}</td><td>${{sHtml}}</td><td><button class="btn btn-sm py-0 ${{bClass}}" onclick="${{bAct}}">${{bText}}</button>${{bReplay}}</td></tr>`;
                    }});
                }}
                html += '</tbody></table>'; document.getElementById('history').innerHTML = html; toggleKillBar(); 
            }}).catch(() => {{}});
        }}
        function killTask(id) {{
            const apiKey = document.getElementById('api-key').value; if (!apiKey) return alert('API Key required');
            if (confirm('Are you sure you want to kill this task?')) {{ fetch(`/tasks/${{id}}/kill`, {{ method: 'POST', headers: {{ 'x-api-key': apiKey }} }}).then(r => {{ if(!r.ok) throw new Error('Kill Failed'); return r.json(); }}).then(d => {{ updateStatus(); updateHistory(); updateStats(); }}).catch(e => alert(e.message)); }}
        }}
        function viewOutput(id) {{
            isViewingHistory = true; const apiKey = document.getElementById('api-key').value || '';
            fetch(`/history/${{id}}/output`, {{headers: {{'x-api-key': apiKey}}}}).then(r => r.json()).then(data => {{ document.getElementById('output').innerHTML = data.output.replace(/\\n/g, '<br>'); }});
        }}
        function viewLiveOutput() {{ isViewingHistory = false; document.getElementById('output').innerHTML = ''; if (ws) ws.send("REQUEST_CURRENT_OUTPUT"); }}
        setInterval(updateStats, 3000); setInterval(updateStatus, 3000); setInterval(updateHistory, 5000); setInterval(updateProjectList, 10000);
    </script>
</head>
<body>
    <nav class="navbar navbar-expand-lg border-bottom mb-4 shadow-sm" style="background-color: var(--bs-body-bg);">
        <div class="container-fluid px-4">
            <a class="navbar-brand text-primary" href="#">🧬 bioWorker Engine <span class="badge bg-secondary ms-2" style="font-size: 0.65rem;">v{server_version}</span></a>
            <div class="d-flex align-items-center">
                <button class="btn btn-sm btn-danger me-3 fw-bold" id="shutdown-btn" onclick="shutdownServer()" style="display: none;">Shutdown Server</button>
                <a href="/admin" class="btn btn-sm btn-outline-danger me-3 fw-bold">Admin</a>
                <button class="btn btn-outline-secondary btn-theme fw-bold" id="theme-toggle" onclick="toggleTheme()">☀️ Light</button>
            </div>
        </div>
    </nav>
    <div class="container-fluid px-4">
        <div class="row mb-3">
            <div class="col-md-3 col-6 mb-2"><div class="card stat-card border-0 bg-primary bg-opacity-10 text-primary h-100"><div class="card-body py-2 px-3 text-center"><div class="small fw-semibold text-uppercase opacity-75">Server Load</div><div class="stat-value" id="sys-load">0.00 | 0.00 | 0.00</div></div></div></div>
            <div class="col-md-3 col-6 mb-2"><div class="card stat-card border-0 bg-info bg-opacity-10 text-info h-100"><div class="card-body py-2 px-3 text-center"><div class="small fw-semibold text-uppercase opacity-75">Server Memory</div><div class="stat-value"><span id="sys-mem">0.0 MB / 0.0 MB</span> <small id="sys-mem-pct" class="fs-6 opacity-75">(0%)</small></div></div></div></div>
            <div class="col-md-3 col-6 mb-2"><div class="card stat-card border-0 bg-success bg-opacity-10 text-success h-100"><div class="card-body py-2 px-3 text-center"><div class="small fw-semibold text-uppercase opacity-75">Project CPU</div><div class="stat-value" id="proj-cpu">0.0%</div></div></div></div>
            <div class="col-md-3 col-6 mb-2"><div class="card stat-card border-0 bg-warning bg-opacity-10 text-warning text-dark h-100"><div class="card-body py-2 px-3 text-center"><div class="small fw-semibold text-uppercase opacity-75">Project Memory</div><div class="stat-value" id="proj-mem">0.0 MB</div></div></div></div>
        </div>
        <div class="row">
            <div class="col-lg-4 col-md-5">
                <div class="card shadow-sm"><div class="card-header d-flex align-items-center"><span class="me-2">🔑</span> Authentication & Routing</div><div class="card-body py-3"><div class="mb-3"><label class="form-label small fw-semibold text-muted d-flex justify-content-between align-items-center">Access API Key <span id="key-indicator"></span></label><input type="password" class="form-control form-control-sm" id="api-key" placeholder="Enter API Key" onkeyup="onKeyInput()" onchange="onKeyInput()"></div><hr class="text-muted"><div class="mb-3"><label class="form-label small fw-semibold text-muted">Active Project Workspace</label>
                <div class="d-flex gap-2 mb-2">
                    <button class="btn btn-sm btn-outline-primary flex-fill fw-semibold" onclick="createProject()">+ New Project</button>
                    <input type="file" id="import-json-file" accept=".json" style="display: none;" onchange="importProject(event)">
                    <button class="btn btn-sm btn-outline-success flex-fill fw-semibold" onclick="document.getElementById('import-json-file').click()">📥 Import JSON</button>
                </div>
                <select class="form-select form-select-sm mb-2" id="project-select" onchange="selectProjectId()"><option value="">Select Existing Project</option></select><input type="text" class="form-control form-control-sm" id="project-id" placeholder="Or enter manual Project ID" onchange="setProjectId()"></div></div></div>
                <div class="card shadow-sm"><div class="card-header d-flex align-items-center"><span class="me-2">🚀</span> Task Execution</div><div class="card-body"><div class="mb-2"><input type="text" class="form-control form-control-sm" id="session-working-dir" placeholder="Global Dir Path (e.g. /home/user)"><button class="btn btn-sm btn-outline-secondary w-100 mt-1" onclick="setWorkingDir()">Set Environment Directory</button></div><hr class="text-muted my-3"><textarea class="form-control form-control-sm mb-2 font-monospace" id="command" rows="3" placeholder="Command to execute..."></textarea><input type="text" class="form-control form-control-sm mb-2" id="working-dir" placeholder="Specific Task Dir (Overrides Environment)"><input type="number" class="form-control form-control-sm mb-3" id="timeout" placeholder="Timeout Limit (Seconds)"><button class="btn btn-primary w-100 fw-bold shadow-sm" onclick="submitCommand()">RUN COMMAND</button></div></div>
            </div>
            <div class="col-lg-8 col-md-7">
                <div class="card shadow-sm"><div class="card-header d-flex justify-content-between align-items-center"><div><span class="me-2">📊</span> Current Project Status</div><span id="status-badge" class="badge bg-secondary rounded-pill">Idle</span></div><div class="card-body py-3" id="status-text"><span class="text-muted">Select a project to view details</span></div></div>
                <div class="card shadow-sm"><div class="card-header d-flex justify-content-between align-items-center"><div><span class="me-2">📜</span> Project Pipeline History</div><div><button class="btn btn-sm btn-outline-primary py-0" onclick="exportHistory('simple', 'md')">📄 Simple</button><button class="btn btn-sm btn-outline-success py-0" onclick="exportHistory('full', 'md')">📑 Full</button><button class="btn btn-sm btn-outline-warning py-0 ms-1" onclick="exportHistory('full', 'json')">JSON</button></div></div><div class="card-body p-0"><div id="bulk-kill-bar" class="bg-danger bg-opacity-10 border-bottom border-danger border-opacity-25 px-3 py-2 align-items-center" style="display: none;"><span class="small fw-bold text-danger me-auto">Bulk Terminate:</span><input type="text" id="kill-message" class="form-control form-control-sm d-inline-block me-2" placeholder="Postscript / Reason (optional)" style="max-width: 250px;"><button class="btn btn-sm btn-danger fw-semibold" onclick="killSelectedTasks()">Kill Selected</button></div><div class="table-responsive" id="history"><table class="table table-sm table-hover mb-0 text-center align-middle"><thead><tr><th style="width:100px;">ID</th><th>Command</th><th>Time</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr><td colspan="5" class="text-muted py-3">No Project Selected</td></tr></tbody></table></div></div></div>
                <div class="card border-0 shadow-sm overflow-hidden rounded-3"><div class="terminal-header"><div><span class="text-success me-2">●</span> Live Console Stream</div><button class="btn btn-sm btn-outline-light py-0 px-2" onclick="viewLiveOutput()" style="font-size: 0.75rem; border-color: rgba(255,255,255,0.2);">Sync Log</button></div><div id="output"></div></div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get(PANEL_PATH, response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    web_port = int(os.environ.get("BIOWORKER_PORT", "38000"))
    uvicorn.run(app, host="0.0.0.0", port=web_port)