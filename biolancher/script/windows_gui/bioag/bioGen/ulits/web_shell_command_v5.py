import os
import signal
import time
import threading
import queue
import subprocess
import asyncio
from typing import Optional, List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Path, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import uuid
import secrets
import json
import base64
import tempfile

server_version = '1.3.0'

app = FastAPI()

# Global state
projects: Dict[
    str, Dict] = {}  # project_id: {"is_running": bool, "current_command": str, "current_output": list, "history": list, "output_queue": queue, "working_dir": str, "manager": ConnectionManager, "current_task_id": str, "current_pid": int, "start_time": float}
loop = None  # Will be set in startup
api_key: str = os.getenv("API_KEY")
log_dir: str = os.getenv("LOG_DIR", os.getcwd())
cmd_history_dir = os.path.join(log_dir, "cmd_history")
os.makedirs(cmd_history_dir, exist_ok=True)
MAX_OUTPUT_LINES = 1000  # Limit output buffer size
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 10))
latest_task_id: Optional[str] = None  # Track the most recently submitted task across all projects
latest_task_project_id: Optional[str] = None  # Track the project of the latest task

# Generate and set API key if not provided
if not api_key:
    api_key = secrets.token_urlsafe(32)
    os.environ["API_KEY"] = api_key
    print(f"Generated API Key (please save this for future use or set in environment variable API_KEY): {api_key}")


class CommandRequest(BaseModel):
    command: str
    timeout: Optional[float] = None
    working_dir: Optional[str] = None
    script_type: Optional[str] = None  # e.g., "python", "r", "perl"
    interpreter: Optional[str] = None
    conda_env: Optional[str] = None


class WorkingDirRequest(BaseModel):
    working_dir: str


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
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


@app.on_event("startup")
async def startup_event():
    global loop
    loop = asyncio.get_running_loop()


def process_output(project_id: str, task_id: str):
    project = projects[project_id]
    while project["is_running"]:
        try:
            line = project["output_queue"].get(timeout=0.1)
            if len(project["current_output"]) >= MAX_OUTPUT_LINES:
                project["current_output"] = project["current_output"][-(MAX_OUTPUT_LINES - 1):]
            project["current_output"].append(line)
            if task_id == latest_task_id:
                asyncio.run_coroutine_threadsafe(project["manager"].broadcast(line), loop)
        except queue.Empty:
            pass


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")


def get_project(project_id: str):
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects[project_id]


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


@app.post("/projects")
async def create_project(x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    project_id = str(uuid.uuid4())
    projects[project_id] = {
        "is_running": False,
        "current_command": "",
        "current_output": [],
        "history": [],
        "output_queue": None,
        "working_dir": None,
        "manager": ConnectionManager(),
        "current_task_id": None,
        "current_pid": None,
        "start_time": None
    }
    return {"project_id": project_id}


@app.get("/projects")
async def get_projects(x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    return {"project_ids": list(projects.keys())}


@app.post("/projects/{project_id}/execute")
async def execute_command(project_id: str = Path(...), request: CommandRequest = None, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    project = get_project(project_id)
    if project["is_running"]:
        raise HTTPException(status_code=409, detail="A command is already running in this project.")

    running_count = sum(1 for p in projects.values() if p["is_running"])
    if running_count >= MAX_CONCURRENT_TASKS:
        raise HTTPException(status_code=503, detail="Server is busy handling maximum concurrent tasks. Please try again later.")

    if request.script_type:
        script_type = request.script_type.lower()
        if script_type not in ["python", "r", "perl"]:
            raise HTTPException(status_code=400, detail="Unsupported script_type. Supported: python, r, perl")

    project["current_command"] = request.command
    project["current_output"] = []
    project["output_queue"] = queue.Queue()
    project["is_running"] = True

    task_id = str(uuid.uuid4())
    project["current_task_id"] = task_id
    global latest_task_id, latest_task_project_id
    latest_task_id = task_id
    latest_task_project_id = project_id

    if task_id == latest_task_id:
        for pid, proj in projects.items():
            asyncio.run_coroutine_threadsafe(proj["manager"].broadcast("CLEAR_OUTPUT"), loop)

    output_thread = threading.Thread(target=process_output, args=(project_id, task_id))
    output_thread.start()

    start_time = time.time()
    project["start_time"] = start_time
    effective_working_dir = request.working_dir or project["working_dir"]

    def run_command():
        temp_file = None
        try:
            cmd = request.command
            if request.script_type:
                script_type = request.script_type.lower()
                ext = {"python": ".py", "r": ".R", "perl": ".pl"}[script_type]
                dir_for_temp = effective_working_dir if effective_working_dir else None
                tf = tempfile.NamedTemporaryFile(suffix=ext, dir=dir_for_temp, delete=False)
                temp_file = tf.name
                tf.write(request.command.encode('utf-8'))
                tf.close()
                interp = request.interpreter or {"python": "python", "r": "Rscript", "perl": "perl"}[script_type]
                cmd = f"{interp} {temp_file}"

            if request.conda_env:
                if os.path.isdir(request.conda_env):
                    conda_flag = "-p"
                else:
                    conda_flag = "-n"
                cmd = f"micromamba run {conda_flag} {request.conda_env} --no-capture-output {cmd}"

            kwargs = {
                "shell": True,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "preexec_fn": os.setsid
            }
            if effective_working_dir and os.path.isdir(effective_working_dir):
                kwargs["cwd"] = effective_working_dir

            proc = subprocess.Popen(cmd, **kwargs)
            project["current_pid"] = proc.pid

            def read_stdout():
                for line in iter(proc.stdout.readline, ''):
                    if project["output_queue"]:
                        project["output_queue"].put(line)

            def read_stderr():
                for line in iter(proc.stderr.readline, ''):
                    if project["output_queue"]:
                        project["output_queue"].put(line)

            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)
            stdout_thread.start()
            stderr_thread.start()

            while proc.poll() is None:
                if request.timeout is not None and time.time() - start_time > request.timeout:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    if project["output_queue"]:
                        project["output_queue"].put("\nTimeout exceeded, process tree killed.\n")
                    break
                time.sleep(0.1)

            stdout_thread.join()
            stderr_thread.join()
            proc.wait()
            returncode = proc.returncode
            project["current_pid"] = None

            end_time = time.time()
            project["is_running"] = False
            full_output = ''.join(project["current_output"])
            history_entry = {
                "id": task_id,
                "command": request.command,
                "working_dir": effective_working_dir,
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "returncode": returncode,
                "output": full_output
            }
            if request.script_type:
                history_entry["script_type"] = request.script_type
            if request.interpreter:
                history_entry["interpreter"] = request.interpreter
            if request.conda_env:
                history_entry["conda_env"] = request.conda_env
            project["history"].append(history_entry)
            save_project_history(project_id)
            project["current_output"] = []
            project["output_queue"] = None
            project["current_task_id"] = None
            project["start_time"] = None
            if task_id == latest_task_id:
                latest_task_id = None
                latest_task_project_id = None
                for pid, proj in projects.items():
                    asyncio.run_coroutine_threadsafe(proj["manager"].broadcast("COMMAND_COMPLETE"), loop)
        finally:
            if temp_file:
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass

    command_thread = threading.Thread(target=run_command)
    command_thread.start()

    return {"message": "Command started", "id": task_id}


@app.post("/projects/{project_id}/set-working-dir")
async def set_working_dir(project_id: str = Path(...), request: WorkingDirRequest = None, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    project = get_project(project_id)
    if not os.path.isdir(request.working_dir):
        raise HTTPException(status_code=400, detail="Invalid working directory")
    project["working_dir"] = request.working_dir
    return {"message": f"Project working directory set to {request.working_dir}"}


@app.get("/projects/{project_id}/status")
async def get_status(project_id: str = Path(...)):
    project = get_project(project_id)
    return {
        "is_running": project["is_running"],
        "current_command": project["current_command"] if project["is_running"] else None,
        "current_task_id": project["current_task_id"] if project["is_running"] else None,
        "status": "running" if project["is_running"] else "idle",
        "working_dir": project["working_dir"]
    }


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    for project_id, project in projects.items():
        if project["is_running"] and project["current_task_id"] == task_id:
            return {
                "task_id": task_id,
                "project_id": project_id,
                "is_running": True,
                "command": project["current_command"],
                "working_dir": project["working_dir"],
                "returncode": None
            }
        for h in project["history"]:
            if h["id"] == task_id:
                return {
                    "task_id": task_id,
                    "project_id": project_id,
                    "is_running": False,
                    "command": h["command"],
                    "working_dir": h["working_dir"],
                    "returncode": h["returncode"]
                }
    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/projects/{project_id}/history")
async def get_history(project_id: str = Path(...)):
    project = get_project(project_id)
    history_list = []
    if project["is_running"]:
        duration = time.time() - project["start_time"]
        history_list.append({
            "id": project["current_task_id"],
            "command": project["current_command"],
            "working_dir": project["working_dir"] or "N/A",
            "duration": duration,
            "returncode": None
        })
    for h in project["history"]:
        entry = {
            "id": h["id"],
            "command": h["command"],
            "working_dir": h["working_dir"] or "N/A",
            "duration": h["duration"],
            "returncode": h["returncode"]
        }
        if "script_type" in h:
            entry["script_type"] = h["script_type"]
        if "interpreter" in h:
            entry["interpreter"] = h["interpreter"]
        if "conda_env" in h:
            entry["conda_env"] = h["conda_env"]
        history_list.append(entry)
    return history_list

allow_read = os.getenv("ALLOW_READ")
allow_write = os.getenv("ALLOW_WRITE")

class FileWriteRequest(BaseModel):
    path: str
    content_base64: str
    mode: str = "binary"  # "text" or "binary"

class FileReadRequest(BaseModel):
    path: str
    mode: str = "binary"  # "text" or "binary"

def check_path_allowed(full_path: str, allowed_str: str, operation: str):
    if allowed_str:
        allowed_dirs = allowed_str.split(';')
        full_real = os.path.realpath(full_path)
        allowed = False
        for d in allowed_dirs:
            d_real = os.path.realpath(d)
            if full_real.startswith(d_real + os.sep) or full_real == d_real:
                allowed = True
                break
        if not allowed:
            raise HTTPException(status_code=403, detail=f"{operation} not allowed to this path.")

@app.post("/projects/{project_id}/write_file")
async def write_file(project_id: str = Path(...), request: FileWriteRequest = None, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    project = get_project(project_id)
    working_dir = project.get("working_dir") or os.getcwd()
    if request.mode not in ["text", "binary"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'text' or 'binary'.")
    
    try:
        full_path = os.path.abspath(os.path.join(working_dir, request.path))
        check_path_allowed(full_path, allow_write, "Write")
        
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        content = base64.b64decode(request.content_base64)
        if request.mode == "text":
            str_content = content.decode("utf-8")
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(str_content)
        else:
            with open(full_path, "wb") as f:
                f.write(content)
        
        return {"message": "File written successfully", "path": full_path}
    except base64.binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding.")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid text content for text mode.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {str(e)}")

@app.post("/projects/{project_id}/read_file")
async def read_file(project_id: str = Path(...), request: FileReadRequest = None, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    project = get_project(project_id)
    working_dir = project.get("working_dir") or os.getcwd()
    if request.mode not in ["text", "binary"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'text' or 'binary'.")
    
    try:
        full_path = os.path.abspath(os.path.join(working_dir, request.path))
        check_path_allowed(full_path, allow_read, "Read")
        
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="File not found.")
        
        if request.mode == "text":
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read().encode("utf-8")
        else:
            with open(full_path, "rb") as f:
                content = f.read()
        
        content_base64 = base64.b64encode(content).decode("utf-8")
        return {"content_base64": content_base64, "path": full_path}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid text content for text mode.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@app.get("/history/{task_id}/output")
async def get_history_output(task_id: str):
    for project in projects.values():
        for h in project["history"]:
            if h["id"] == task_id:
                return {"output": h["output"]}
    raise HTTPException(status_code=404, detail="Command not found")


@app.get("/tasks")
async def get_all_tasks(x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    all_tasks = []
    for pid, project in projects.items():
        if project["is_running"]:
            duration = time.time() - project["start_time"]
            all_tasks.append({
                "task_id": project["current_task_id"],
                "project_id": pid,
                "command": project["current_command"],
                "status": "running",
                "duration": duration,
                "returncode": None
            })
        for h in project["history"]:
            entry = {
                "task_id": h["id"],
                "project_id": pid,
                "command": h["command"],
                "status": "completed",
                "duration": h["duration"],
                "returncode": h["returncode"]
            }
            if "script_type" in h:
                entry["script_type"] = h["script_type"]
            if "interpreter" in h:
                entry["interpreter"] = h["interpreter"]
            if "conda_env" in h:
                entry["conda_env"] = h["conda_env"]
            all_tasks.append(entry)
    return all_tasks

@app.get("/status/project/{project_id}")
async def get_status(project_id: str, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    ## if task running, return running status
    project = get_project(project_id)
    if project["is_running"]:
        return {
            "status": "running",
            "current_command": project["current_command"],
            "current_task_id": project["current_task_id"],
            "working_dir": project["working_dir"]
        }
    else:
        return {
            "status": "idle",
            "current_command": None,
            "current_task_id": None,
            "working_dir": project["working_dir"]
        }

@app.post("/tasks/{task_id}/kill")
async def kill_task(task_id: str = Path(...), x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    for pid, project in projects.items():
        if project["is_running"] and project["current_task_id"] == task_id:
            current_pid = project.get("current_pid")
            if current_pid:
                try:
                    os.killpg(os.getpgid(current_pid), signal.SIGTERM)
                    if project["output_queue"]:
                        project["output_queue"].put("\nCommand killed by user.\n")
                    return {"message": "Kill signal sent"}
                except OSError:
                    raise HTTPException(status_code=500, detail="Failed to kill process")
            else:
                raise HTTPException(status_code=500, detail="No process ID found")
    raise HTTPException(status_code=404, detail="Task not running")


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str = Path(...)):
    project = get_project(project_id)
    is_latest_task = project["is_running"] and project["current_task_id"] == latest_task_id
    await project["manager"].connect(websocket, project["current_output"], is_latest_task)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "REQUEST_CURRENT_OUTPUT" and project["is_running"] and project[
                "current_task_id"] == latest_task_id:
                await websocket.send_text(''.join(project["current_output"]))
            elif data == "REQUEST_CURRENT_OUTPUT":
                await websocket.send_text("")
    except WebSocketDisconnect:
        project["manager"].disconnect(websocket)


@app.post("/shutdown")
async def shutdown(background_tasks: BackgroundTasks, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    if os.environ.get("ALLOW_SHUTDOWN", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Shutdown not allowed. Set ALLOW_SHUTDOWN=true to enable.")
    background_tasks.add_task(lambda: os.kill(os.getpid(), signal.SIGTERM))
    exit(0)
    return {"message": "Shutdown initiated"}


# Simple visualization panel
html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Command Execution Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script>
        let ws = null;
        let currentProjectId = '';
        let isViewingHistory = false;
        function connectWebSocket(projectId) {
            if (ws) ws.close();
            ws = new WebSocket("ws://" + window.location.host + "/ws/" + projectId);
            ws.onmessage = function(event) {
                const outputDiv = document.getElementById('output');
                if (isViewingHistory) return;
                if (event.data === "CLEAR_OUTPUT" || event.data === "COMMAND_COMPLETE") {
                    outputDiv.innerHTML = '';
                } else {
                    outputDiv.innerHTML += event.data.replace(/\\n/g, '<br>');
                    outputDiv.scrollTop = outputDiv.scrollHeight;
                }
            };
            ws.onopen = function() {
                if (!isViewingHistory) ws.send("REQUEST_CURRENT_OUTPUT");
            };
            ws.onclose = function() {
                if (currentProjectId && !isViewingHistory) setTimeout(() => connectWebSocket(currentProjectId), 1000);
            };
        }
        window.onload = function() {
            updateStatus();
            updateHistory();
            updateProjectList();
        };
        function createProject() {
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            fetch('/projects', {
                method: 'POST',
                headers: {
                    'x-api-key': apiKey
                }
            }).then(response => {
                if (!response.ok) throw new Error('Failed to create project');
                return response.json();
            }).then(data => {
                currentProjectId = data.project_id;
                document.getElementById('project-id').value = currentProjectId;
                alert('Project created: ' + currentProjectId.slice(0, 8) + '...');
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                updateStatus();
                updateHistory();
                updateProjectList();
            }).catch(error => {
                alert('Error: ' + error.message);
            });
        }
        function setProjectId() {
            currentProjectId = document.getElementById('project-id').value;
            if (currentProjectId) {
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                document.getElementById('output').innerHTML = '';
                updateStatus();
                updateHistory();
            }
        }
        function selectProjectId() {
            currentProjectId = document.getElementById('project-select').value;
            if (currentProjectId) {
                document.getElementById('project-id').value = currentProjectId;
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                document.getElementById('output').innerHTML = '';
                updateStatus();
                updateHistory();
            }
        }
        function updateProjectList() {
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) return;
            fetch('/projects', {
                headers: {
                    'x-api-key': apiKey
                }
            }).then(response => {
                if (!response.ok) return;
                return response.json();
            }).then(data => {
                const select = document.getElementById('project-select');
                select.innerHTML = '<option value="">Select a project</option>';
                if (data && data.project_ids) {
                    data.project_ids.forEach(id => {
                        const option = document.createElement('option');
                        option.value = id;
                        option.text = id.slice(0, 8) + '...';
                        select.appendChild(option);
                    });
                    if (currentProjectId) {
                        select.value = currentProjectId;
                    }
                }
            }).catch(() => {});
        }
        function submitCommand() {
            if (!currentProjectId) {
                alert('Project ID is required');
                return;
            }
            const command = document.getElementById('command').value;
            const timeout = document.getElementById('timeout').value;
            const workingDir = document.getElementById('working-dir').value;
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            fetch(`/projects/${currentProjectId}/execute`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-api-key': apiKey
                },
                body: JSON.stringify({
                    command: command,
                    timeout: timeout ? parseFloat(timeout) : null,
                    working_dir: workingDir || null
                })
            }).then(response => {
                if (!response.ok) throw new Error('Failed to execute command');
                return response.json();
            }).then(data => {
                alert(data.message + ' (Task ID: ' + data.id.slice(0, 8) + '...)');
                isViewingHistory = false;
                updateStatus();
                updateHistory();
            }).catch(error => {
                alert('Error: ' + error.message);
            });
        }
        function setWorkingDir() {
            if (!currentProjectId) {
                alert('Project ID is required');
                return;
            }
            const workingDir = document.getElementById('session-working-dir').value;
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            fetch(`/projects/${currentProjectId}/set-working-dir`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-api-key': apiKey
                },
                body: JSON.stringify({working_dir: workingDir})
            }).then(response => {
                if (!response.ok) throw new Error('Failed to set working directory');
                return response.json();
            }).then(data => {
                alert(data.message);
                updateStatus();
            }).catch(error => {
                alert('Error: ' + error.message);
            });
        }
        function updateStatus() {
            if (!currentProjectId) {
                document.getElementById('status').innerText = 'Status: Select a project';
                return;
            }
            fetch(`/projects/${currentProjectId}/status`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('status').innerText = `Status: ${data.status} ${data.current_command ? '- ' + data.current_command : ''} ${data.working_dir ? '(Working Dir: ' + data.working_dir + ')' : ''}`;
            }).catch(() => {});
        }
        function updateHistory() {
            if (!currentProjectId) {
                document.getElementById('history').innerHTML = '';
                return;
            }
            fetch(`/projects/${currentProjectId}/history`)
            .then(response => response.json())
            .then(data => {
                const historyList = document.getElementById('history');
                historyList.innerHTML = '';
                data.forEach(item => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item';
                    let buttons = '';
                    if (item.returncode === null) {
                        buttons = `<button class="btn btn-sm btn-danger" onclick="killTask('${item.id}')">Kill</button>
                                   <button class="btn btn-sm btn-secondary" onclick="viewStatus('${item.id}')">View Status</button>`;
                    } else {
                        buttons = `<button class="btn btn-sm btn-info" onclick="viewOutput('${item.id}')">View Output</button>
                                   <button class="btn btn-sm btn-secondary" onclick="viewStatus('${item.id}')">View Status</button>`;
                    }
                    li.innerHTML = `ID: ${item.id.slice(0, 8)}... | Command: ${item.command} | Working Dir: ${item.working_dir || 'N/A'} | Duration: ${item.duration ? item.duration.toFixed(2) + 's' : 'Running'} | Return Code: ${item.returncode ?? 'N/A'}
                                    ${buttons}`;
                    historyList.appendChild(li);
                });
            }).catch(() => {});
        }
        function killTask(id) {
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            if (confirm('Are you sure you want to kill this task?')) {
                fetch(`/tasks/${id}/kill`, {
                    method: 'POST',
                    headers: {
                        'x-api-key': apiKey
                    }
                }).then(response => {
                    if (!response.ok) throw new Error('Failed to kill task');
                    return response.json();
                }).then(data => {
                    alert(data.message);
                    updateStatus();
                    updateHistory();
                }).catch(error => {
                    alert('Error: ' + error.message);
                });
            }
        }
        function viewOutput(id) {
            isViewingHistory = true;
            fetch(`/history/${id}/output`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('output').innerHTML = data.output.replace(/\\n/g, '<br>');
            });
        }
        function viewStatus(id) {
            fetch(`/status/${id}`)
            .then(response => response.json())
            .then(data => {
                alert(`Task ID: ${data.task_id.slice(0, 8)}...\nProject ID: ${data.project_id.slice(0, 8)}...\nCommand: ${data.command}\nWorking Dir: ${data.working_dir || 'N/A'}\nStatus: ${data.is_running ? 'Running' : 'Completed'}\nReturn Code: ${data.returncode ?? 'N/A'}`);
            });
        }
        function viewLiveOutput() {
            isViewingHistory = false;
            document.getElementById('output').innerHTML = '';
            if (ws) ws.send("REQUEST_CURRENT_OUTPUT");
        }
        setInterval(updateStatus, 2000);
        setInterval(updateHistory, 5000);
        setInterval(updateProjectList, 10000);
    </script>
</head>
<body>
    <div class="container mt-5">
        <h1 class="mb-4">Command Execution Panel</h1>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">API Key</h5>
                <div class="mb-3">
                    <label for="api-key" class="form-label">API Key</label>
                    <input type="text" class="form-control" id="api-key" placeholder="Enter your API key" onchange="updateProjectList()">
                </div>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Project Management</h5>
                <button type="button" class="btn btn-primary mb-3" onclick="createProject()">Create New Project</button>
                <div class="mb-3">
                    <label for="project-select" class="form-label">Select Existing Project</label>
                    <select class="form-control" id="project-select" onchange="selectProjectId()">
                        <option value="">Select a project</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="project-id" class="form-label">Project ID</label>
                    <input type="text" class="form-control" id="project-id" placeholder="Enter or paste project ID" onchange="setProjectId()">
                </div>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Set Project Working Directory</h5>
                <div class="mb-3">
                    <label for="session-working-dir" class="form-label">Working Directory</label>
                    <input type="text" class="form-control" id="session-working-dir" placeholder="e.g., /path/to/dir">
                </div>
                <button type="button" class="btn btn-primary" onclick="setWorkingDir()">Set Working Directory</button>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Submit Command</h5>
                <form>
                    <div class="mb-3">
                        <label for="command" class="form-label">Command</label>
                        <input type="text" class="form-control" id="command" placeholder="e.g., echo Hello World">
                    </div>
                    <div class="mb-3">
                        <label for="working-dir" class="form-label">Working Directory (optional)</label>
                        <input type="text" class="form-control" id="working-dir" placeholder="e.g., /path/to/dir (overrides project working dir)">
                    </div>
                    <div class="mb-3">
                        <label for="timeout" class="form-label">Timeout (seconds, optional)</label>
                        <input type="number" class="form-control" id="timeout" placeholder="e.g., 10">
                    </div>
                    <button type="button" class="btn btn-primary" onclick="submitCommand()">Execute</button>
                </form>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Status</h5>
                <p id="status">Status: Select a project</p>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Execution History</h5>
                <button type="button" class="btn btn-primary mb-3" onclick="viewLiveOutput()">View Live Output</button>
                <ul id="history" class="list-group"></ul>
            </div>
        </div>
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Live Console Output</h5>
                <div id="output" class="bg-dark text-white p-3" style="height: 300px; overflow-y: auto; white-space: pre-wrap;"></div>
            </div>
        </div>
    </div>
</body>
""" + f"""
<div style='position: fixed; bottom: 10px; font-size: 10px; color: grey;'>bioWorker Version: {server_version}</div>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    print('Success start the bioWorker API server')
    web_port = int(os.environ.get("BIOWORKER_PORT", "38000"))
    uvicorn.run(app, host="0.0.0.0", port=web_port)