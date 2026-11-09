import os
import signal
import time
import threading
import queue
import subprocess
import asyncio
from typing import Optional, List, Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Path, BackgroundTasks, Depends, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import uuid
import secrets
import json
import tempfile

app = FastAPI()

# Global state
projects: Dict[str, Dict] = {}  # project_id: { ... , "api_keys": set[str] }
loop = None
api_key: str = os.getenv("API_KEY")
log_dir: str = os.getenv("LOG_DIR", os.getcwd())
cmd_history_dir = os.path.join(log_dir, "cmd_history")
os.makedirs(cmd_history_dir, exist_ok=True)
MAX_OUTPUT_LINES = 1000
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 10))
latest_task_id: Optional[str] = None
latest_task_project_id: Optional[str] = None

server_version = "v1.1.9"

# Generate and set master API key if not provided
if not api_key:
    api_key = secrets.token_urlsafe(32)
    os.environ["API_KEY"] = api_key
    print(f"Generated Master API Key (save it!): {api_key}")

class CommandRequest(BaseModel):
    command: str
    timeout: Optional[float] = None
    working_dir: Optional[str] = None
    script_type: Optional[str] = None
    interpreter: Optional[str] = None
    conda_env: Optional[str] = None

class WorkingDirRequest(BaseModel):
    working_dir: str

class KillRequest(BaseModel):
    message: Optional[str] = None

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

# ====================== Authentication ======================
def get_auth(x_api_key: str = Header(..., alias="x-api-key")) -> Dict[str, Optional[str]]:
    if x_api_key == api_key:
        return {"role": "admin", "bound_project": None}

    for pid, project in projects.items():
        if x_api_key in project.get("api_keys", set()):
            return {"role": "user", "bound_project": pid}

    raise HTTPException(status_code=401, detail="Invalid API Key")

def get_project_with_auth(
    project_id: str = Path(...),
    auth: Dict[str, Optional[str]] = Depends(get_auth)
) -> Dict:
    if auth["role"] == "user" and auth["bound_project"] != project_id:
        raise HTTPException(status_code=403, detail="API key not authorized for this project")
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects[project_id]

# ====================== New APIs ======================
@app.get("/version")
async def get_version(auth: Dict = Depends(get_auth)):
    return {"version": server_version}

@app.post("/projects/{project_id}/api-keys")
async def generate_project_api_key(
    project_id: str = Path(...),
    auth: Dict = Depends(get_auth)
):
    if auth["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can generate project API keys")
    
    project = projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    new_key = secrets.token_urlsafe(32)
    if "api_keys" not in project:
        project["api_keys"] = set()
    project["api_keys"].add(new_key)
    
    print(f"Generated Project API Key for {project_id}: {new_key}")
    return {"project_api_key": new_key, "bound_project_id": project_id}

class ImportToolsRequest(BaseModel):
    json_file: str

@app.post("/projects/{project_id}/import-tools")
async def import_tools(
    project_id: str = Path(...),
    request: ImportToolsRequest = Body(...),
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    
    if project["working_dir"] is None:
        raise HTTPException(status_code=400, detail="Working directory not set")
    
    json_path = request.json_file
    if not os.path.isabs(json_path):
        json_path = os.path.join(project["working_dir"], json_path)
    
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="JSON file not found")
    
    with open(json_path, 'r') as f:
        tools = json.load(f)
    
    # Validate JSON
    if not isinstance(tools, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON format: must be a dictionary")
    
    for tool_key, tool_info in tools.items():
        if not isinstance(tool_info, dict) or 'name' not in tool_info or 'description' not in tool_info or 'script' not in tool_info:
            raise HTTPException(status_code=400, detail=f"Invalid tool format for '{tool_key}': must have 'name', 'description', and 'script'")
    
    script_folder = os.path.join(project["working_dir"], f"{project_id}_scripts")
    os.makedirs(script_folder, exist_ok=True)
    
    for tool_key, tool_info in tools.items():
        script_path = os.path.join(script_folder, tool_info['name'])
        with open(script_path, 'w') as f:
            f.write(tool_info['script'])
        os.chmod(script_path, 0o755)  # Make executable
    
    project["tools"] = tools
    project["script_dir"] = script_folder
    
    return {"message": "Tools imported successfully"}

@app.get("/projects/{project_id}/tools")
async def get_tools(
    project_id: str = Path(...),
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    return {"tools": project.get("tools", {})}

class EnvVarsRequest(BaseModel):
    env_vars: Dict[str, str]

@app.post("/projects/{project_id}/env-vars")
async def set_env_vars(
    project_id: str = Path(...),
    request: EnvVarsRequest = Body(...),
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    project["env_vars"].update(request.env_vars)
    return {"message": "Environment variables updated"}

@app.get("/projects/{project_id}/env-vars")
async def get_env_vars(
    project_id: str = Path(...),
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    return {"env_vars": project["env_vars"]}

# ====================== Existing APIs (modified) ======================
@app.post("/projects")
async def create_project(auth: Dict = Depends(get_auth)):
    if auth["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can create projects")
    
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
        "start_time": None,
        "api_keys": set(),
        "env_vars": {}
    }
    return {"project_id": project_id}

@app.get("/projects")
async def get_projects(auth: Dict = Depends(get_auth)):
    if auth["role"] == "admin":
        return {"project_ids": list(projects.keys())}
    else:
        return {"project_ids": [auth["bound_project"]]}

@app.post("/projects/{project_id}/execute")
async def execute_command(
    project_id: str = Path(...),
    request: CommandRequest = None,
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    
    if project["is_running"]:
        raise HTTPException(status_code=409, detail="A command is already running in this project.")

    running_count = sum(1 for p in projects.values() if p["is_running"])
    if running_count >= MAX_CONCURRENT_TASKS:
        raise HTTPException(status_code=503, detail="Server is busy handling maximum concurrent tasks.")

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

            env = os.environ.copy()
            env.update(project["env_vars"])
            if "script_dir" in project:
                env['PATH'] = project["script_dir"] + ':' + env.get('PATH', '')
            kwargs["env"] = env

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
async def set_working_dir(
    project_id: str = Path(...),
    request: WorkingDirRequest = None,
    auth: Dict = Depends(get_auth)
):
    project = get_project_with_auth(project_id, auth)
    if not os.path.isdir(request.working_dir):
        raise HTTPException(status_code=400, detail="Invalid working directory")
    project["working_dir"] = request.working_dir
    return {"message": f"Project working directory set to {request.working_dir}"}

@app.get("/projects/{project_id}/status")
async def get_status(project_id: str = Path(...), auth: Dict = Depends(get_auth)):
    project = get_project_with_auth(project_id, auth)
    return {
        "is_running": project["is_running"],
        "current_command": project["current_command"] if project["is_running"] else None,
        "current_task_id": project["current_task_id"] if project["is_running"] else None,
        "status": "running" if project["is_running"] else "idle",
        "working_dir": project["working_dir"]
    }

@app.get("/tasks")
async def get_all_tasks(auth: Dict = Depends(get_auth)):
    all_tasks = []
    target_projects = projects.items() if auth["role"] == "admin" else \
        [(auth["bound_project"], projects[auth["bound_project"]])] if auth["bound_project"] in projects else []

    for pid, project in target_projects:
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

@app.post("/tasks/{task_id}/kill")
async def kill_task(
    task_id: str = Path(...),
    kill_request: Optional[KillRequest] = None,
    auth: Dict = Depends(get_auth)
):
    for pid, project in projects.items():
        if project["is_running"] and project["current_task_id"] == task_id:
            if auth["role"] == "user" and auth["bound_project"] != pid:
                raise HTTPException(status_code=403, detail="Not authorized to kill this task")
            
            current_pid = project.get("current_pid")
            if current_pid:
                try:
                    os.killpg(os.getpgid(current_pid), signal.SIGTERM)
                    user_msg = kill_request.message if kill_request and kill_request.message else None
                    put_msg = f"\nCommand killed by user: {user_msg}\n" if user_msg else "\nCommand killed by user.\n"
                    if project["output_queue"]:
                        project["output_queue"].put(put_msg)
                    return {"message": "Kill signal sent"}
                except OSError:
                    raise HTTPException(status_code=500, detail="Failed to kill process")
            else:
                raise HTTPException(status_code=500, detail="No process ID found")
    raise HTTPException(status_code=404, detail="Task not running")

@app.post("/shutdown")
async def shutdown(background_tasks: BackgroundTasks, auth: Dict = Depends(get_auth)):
    if auth["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can shutdown")
    if os.environ.get("ALLOW_SHUTDOWN", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Shutdown not allowed. Set ALLOW_SHUTDOWN=true.")
    background_tasks.add_task(lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"message": "Shutdown initiated"}

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
    project = projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
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

@app.get("/history/{task_id}/output")
async def get_history_output(task_id: str):
    for project in projects.values():
        for h in project["history"]:
            if h["id"] == task_id:
                return {"output": h["output"]}
    raise HTTPException(status_code=404, detail="Command not found")

@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str = Path(...)):
    if project_id not in projects:
        await websocket.close(code=1008)
        return
    project = projects[project_id]
    is_latest_task = project["is_running"] and project["current_task_id"] == latest_task_id
    await project["manager"].connect(websocket, project["current_output"], is_latest_task)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "REQUEST_CURRENT_OUTPUT" and project["is_running"] and project["current_task_id"] == latest_task_id:
                await websocket.send_text(''.join(project["current_output"]))
            elif data == "REQUEST_CURRENT_OUTPUT":
                await websocket.send_text("")
    except WebSocketDisconnect:
        project["manager"].disconnect(websocket)

# ====================== UI (unchanged) ======================
html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Command Execution Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        #output { background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; }
    </style>
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
                    outputDiv.innerHTML += event.data.replace(/\n/g, '<br>');
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
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey) { alert('API Key is required'); return; }
            fetch('/projects', {
                method: 'POST',
                headers: { 'x-api-key': apiKey }
            }).then(r => { if (!r.ok) throw new Error('Failed'); return r.json(); })
              .then(data => {
                  currentProjectId = data.project_id;
                  document.getElementById('project-id').value = currentProjectId;
                  alert('Project created: ' + currentProjectId.slice(0, 8) + '...');
                  isViewingHistory = false;
                  connectWebSocket(currentProjectId);
                  updateStatus(); updateHistory(); updateProjectList();
              }).catch(e => alert('Error: ' + e.message));
        }

        function setProjectId() {
            currentProjectId = document.getElementById('project-id').value.trim();
            if (currentProjectId) {
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                document.getElementById('output').innerHTML = '';
                updateStatus(); updateHistory();
            }
        }

        function selectProjectId() {
            currentProjectId = document.getElementById('project-select').value;
            if (currentProjectId) {
                document.getElementById('project-id').value = currentProjectId;
                isViewingHistory = false;
                connectWebSocket(currentProjectId);
                document.getElementById('output').innerHTML = '';
                updateStatus(); updateHistory();
            }
        }

        function updateProjectList() {
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey) return;
            fetch('/projects', { headers: { 'x-api-key': apiKey } })
                .then(r => { if (!r.ok) return; return r.json(); })
                .then(data => {
                    const select = document.getElementById('project-select');
                    select.innerHTML = '<option value="">Select a project</option>';
                    if (data && data.project_ids) {
                        data.project_ids.forEach(id => {
                            const opt = document.createElement('option');
                            opt.value = id; opt.text = id.slice(0, 8) + '...';
                            select.appendChild(opt);
                        });
                        if (currentProjectId) select.value = currentProjectId;
                    }
                }).catch(() => {});
        }

        function submitCommand() {
            if (!currentProjectId) { alert('Project ID is required'); return; }
            const command = document.getElementById('command').value;
            const timeout = document.getElementById('timeout').value;
            const workingDir = document.getElementById('working-dir').value;
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey) { alert('API Key is required'); return; }

            fetch(`/projects/${currentProjectId}/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey },
                body: JSON.stringify({
                    command: command,
                    timeout: timeout ? parseFloat(timeout) : null,
                    working_dir: workingDir || null
                })
            }).then(r => { if (!r.ok) throw new Error('Failed'); return r.json(); })
              .then(data => {
                  alert(data.message + ' (Task ID: ' + data.id.slice(0, 8) + '...)');
                  isViewingHistory = false;
                  updateStatus(); updateHistory();
              }).catch(e => alert('Error: ' + e.message));
        }

        function setWorkingDir() {
            if (!currentProjectId) { alert('Project ID is required'); return; }
            const workingDir = document.getElementById('session-working-dir').value;
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey) { alert('API Key is required'); return; }

            fetch(`/projects/${currentProjectId}/set-working-dir`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey },
                body: JSON.stringify({ working_dir: workingDir })
            }).then(r => { if (!r.ok) throw new Error('Failed'); return r.json(); })
              .then(data => { alert(data.message); updateStatus(); })
              .catch(e => alert('Error: ' + e.message));
        }

        function updateStatus() {
            if (!currentProjectId) {
                document.getElementById('status').innerText = 'Status: Select a project';
                return;
            }
            fetch(`/projects/${currentProjectId}/status`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status').innerText = 
                        `Status: ${data.status} ${data.current_command ? '- ' + data.current_command : ''} ${data.working_dir ? '(Dir: ' + data.working_dir + ')' : ''}`;
                }).catch(() => {});
        }

        function updateHistory() {
            if (!currentProjectId) { document.getElementById('history').innerHTML = ''; return; }
            fetch(`/projects/${currentProjectId}/history`)
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('history');
                    list.innerHTML = '';
                    data.forEach(item => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item d-flex justify-content-between align-items-center';
                        let buttons = '';
                        if (item.returncode === null) {
                            buttons = `<button class Thickness="btn btn-sm btn-danger me-2" onclick="killTask('${item.id}')">Kill</button>
                                       <button class="btn btn-sm btn-secondary" onclick="viewStatus('${item.id}')">Status</button>`;
                        } else {
                            buttons = `<button class="btn btn-sm btn-info me-2" onclick="viewOutput('${item.id}')">Output</button>
                                       <button class="btn btn-sm btn-secondary" onclick="viewStatus('${item.id}')">Status</button>`;
                        }
                        li.innerHTML = `
                            <span>
                                ID: ${item.id.slice(0, 8)}... | ${item.command.substring(0, 60)}${item.command.length > 60 ? '...' : ''}<br>
                                Dir: ${item.working_dir || 'N/A'} | 
                                Time: ${item.duration ? item.duration.toFixed(2) + 's' : 'Running'} | 
                                Code: ${item.returncode ?? 'N/A'}
                            </span>
                            <span>${buttons}</span>`;
                        list.appendChild(li);
                    });
                }).catch(() => {});
        }

        // ==================== Kill task with optional message ====================
        function killTask(id) {
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey) { alert('API Key is required'); return; }

            const userMessage = prompt('Kill this task?\n\n(Optional) Enter a message to show in output:', '');
            if (userMessage === null) return; // cancelled

            const trimmed = userMessage.trim();
            const hasMessage = trimmed.length > 0;

            const options = {
                method: 'POST',
                headers: { 'x-api-key': apiKey }
            };
            if (hasMessage) {
                options.headers['Content-Type'] = 'application/json';
                options.body = JSON.stringify({ message: trimmed });
            }

            fetch(`/tasks/${id}/kill`, options)
                .then(r => {
                    if (!r.ok) return r.json().then(err => { throw new Error(err.detail || 'Failed'); });
                    return r.json();
                })
                .then(data => {
                    alert(data.message || 'Kill signal sent');
                    updateStatus(); updateHistory();
                })
                .catch(e => alert('Error: ' + e.message));
        }
        // ===================================================================

        function viewOutput(id) {
            isViewingHistory = true;
            fetch(`/history/${id}/output`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('output').innerHTML = data.output.replace(/\n/g, '<br>');
                    document.getElementById('output').scrollTop = 0;
                });
        }

        function viewStatus(id) {
            fetch(`/status/${id}`)
                .then(r => r.json())
                .then(data => {
                    alert(`Task ID: ${data.task_id.slice(0, 8)}...\nProject: ${data.project_id.slice(0, 8)}...\nCommand: ${data.command}\nDir: ${data.working_dir || 'N/A'}\nRunning: ${data.is_running}\nCode: ${data.returncode ?? 'N/A'}`);
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
                <input type="text" class="form-control" id="api-key" placeholder="Enter your API key" onchange="updateProjectList()">
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Project Management</h5>
                <button class="btn btn-primary mb-3" onclick="createProject()">Create New Project</button>
                <div class="row">
                    <div class="col-md-6">
                        <label class="form-label">Select Existing Project</label>
                        <select class="form-select" id="project-select" onchange="selectProjectId()">
                            <option value="">Select a project</option>
                        </select>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Or Enter Project ID</label>
                        <input type="text" class="form-control" id="project-id" placeholder="Paste project ID" onchange="setProjectId()">
                    </div>
                </div>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Set Project Working Directory</h5>
                <div class="row">
                    <div class="col-md-10">
                        <input type="text" class="form-control" id="session-working-dir" placeholder="/path/to/dir">
                    </div>
                    <div class="col-md-2">
                        <button class="btn btn-primary w-100" onclick="setWorkingDir()">Set</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Execute Command</h5>
                <div class="row g-3">
                    <div class="col-12"><input type="text" class="form-control" id="command" placeholder="Command"></div>
                    <div class="col-md-6"><input type="text" class="form-control" id="working-dir" placeholder="One-time working dir (optional)"></div>
                    <div class="col-md-3"><input type="number" class="form-control" id="timeout" placeholder="Timeout (s)"></div>
                    <div class="col-md-3"><button class="btn btn-success w-100" onclick="submitCommand()">Run</button></div>
                </div>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Status</h5>
                <p id="status" class="mb-0">Status: Select a project</p>
            </div>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">History</h5>
                <button class="btn btn-primary mb-3" onclick="viewLiveOutput()">View Live Output</button>
                <ul id="history" class="list-group"></ul>
            </div>
        </div>

        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Console Output</h5>
                <div id="output" class="p-3 rounded" style="height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;"></div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    print('Success start the bioWorker API server')
    uvicorn.run(app, host="0.0.0.0", port=38000)