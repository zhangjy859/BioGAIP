import os
import signal
import time
import threading
import queue
import subprocess
import asyncio
from typing import Optional, List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import uuid
import secrets

app = FastAPI()

# Global state
is_running: bool = False
current_command: str = ""
current_output: List[str] = []
history: List[Dict] = []
output_queue: queue.Queue = queue.Queue()
manager = None  # Will be initialized later
loop = None  # Will be set in startup
session_working_dir: Optional[str] = None
api_key: str = os.getenv("API_KEY")

# Generate and print API key if not set
if not api_key:
    api_key = secrets.token_urlsafe(32)
    print(f"Generated API Key (please set in environment variable API_KEY for future use): {api_key}")


class CommandRequest(BaseModel):
    command: str
    timeout: Optional[float] = None
    working_dir: Optional[str] = None


class WorkingDirRequest(BaseModel):
    working_dir: str


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send current output history to new connection
        await websocket.send_text(''.join(current_output))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


@app.on_event("startup")
async def startup_event():
    global loop, manager
    loop = asyncio.get_running_loop()
    manager = ConnectionManager()


def run_shell_command(command: str, timeout: Optional[float] = None, output_queue: Optional[queue.Queue] = None,
                      working_dir: Optional[str] = None) -> int:
    """
    Executes a shell command, sends stdout and stderr to output_queue in real-time,
    and kills the process tree if timeout is exceeded.

    :param command: The shell command to execute (str).
    :param timeout: Optional timeout in seconds (int or float). If exceeded, kill the process tree.
    :param output_queue: Optional queue to put output lines into.
    :param working_dir: Optional working directory for the command.
    :return: Return code of the process.
    """
    kwargs = {
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "preexec_fn": os.setsid  # Create a new process group for killing the tree
    }
    if working_dir and os.path.isdir(working_dir):
        kwargs["cwd"] = working_dir
    elif session_working_dir and os.path.isdir(session_working_dir):
        kwargs["cwd"] = session_working_dir

    proc = subprocess.Popen(command, **kwargs)

    # Threads to read and put stdout and stderr into the queue
    def read_stdout():
        for line in iter(proc.stdout.readline, ''):
            if output_queue:
                output_queue.put(line)
            # Optional: print(line, end='')

    def read_stderr():
        for line in iter(proc.stderr.readline, ''):
            if output_queue:
                output_queue.put(line)
            # Optional: print(line, end='')

    stdout_thread = threading.Thread(target=read_stdout)
    stderr_thread = threading.Thread(target=read_stderr)
    stdout_thread.start()
    stderr_thread.start()

    # Monitor for timeout
    start_time = time.time()
    while proc.poll() is None:
        if timeout is not None and time.time() - start_time > timeout:
            # Kill the entire process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            if output_queue:
                output_queue.put("\nTimeout exceeded, process tree killed.\n")
            break
        time.sleep(0.1)

    # Wait for threads to finish
    stdout_thread.join()
    stderr_thread.join()

    # Wait for process to terminate
    proc.wait()

    return proc.returncode


def process_output():
    global is_running
    while is_running or not output_queue.empty():
        try:
            line = output_queue.get(timeout=0.1)
            current_output.append(line)
            asyncio.run_coroutine_threadsafe(manager.broadcast(line), loop)
        except queue.Empty:
            pass


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")


@app.post("/execute")
async def execute_command(request: CommandRequest, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    global is_running, current_command, current_output, output_queue
    if is_running:
        raise HTTPException(status_code=409, detail="A command is already running.")

    current_command = request.command
    current_output = []
    output_queue = queue.Queue()  # New queue for this command
    is_running = True

    # Generate unique task ID
    task_id = str(uuid.uuid4())

    # Start output processing thread
    output_thread = threading.Thread(target=process_output)
    output_thread.start()

    start_time = time.time()

    def run_command():
        global is_running
        returncode = run_shell_command(request.command, request.timeout, output_queue, request.working_dir)
        end_time = time.time()
        is_running = False
        full_output = ''.join(current_output)
        history.append({
            "id": task_id,
            "command": request.command,
            "working_dir": request.working_dir or session_working_dir,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
            "returncode": returncode,
            "output": full_output
        })

    # Start command execution in background thread
    command_thread = threading.Thread(target=run_command)
    command_thread.start()

    return {"message": "Command started", "id": task_id}


@app.post("/set-working-dir")
async def set_working_dir(request: WorkingDirRequest, x_api_key: str = Header(...)):
    verify_api_key(x_api_key)
    global session_working_dir
    if not os.path.isdir(request.working_dir):
        raise HTTPException(status_code=400, detail="Invalid working directory")
    session_working_dir = request.working_dir
    return {"message": f"Session working directory set to {request.working_dir}"}


@app.get("/status")
async def get_status():
    return {
        "is_running": is_running,
        "current_command": current_command if is_running else None,
        "status": "running" if is_running else "idle",
        "working_dir": session_working_dir
    }


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    if is_running and history and history[-1]["id"] == task_id:
        return {
            "task_id": task_id,
            "is_running": True,
            "command": current_command,
            "working_dir": history[-1]["working_dir"] if history else session_working_dir,
            "returncode": None
        }
    for h in history:
        if h["id"] == task_id:
            return {
                "task_id": task_id,
                "is_running": False,
                "command": h["command"],
                "working_dir": h["working_dir"],
                "returncode": h["returncode"]
            }
    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/history")
async def get_history():
    # Return history without full output to keep response light
    return [{"id": h["id"], "command": h["command"], "working_dir": h["working_dir"], "duration": h["duration"],
             "returncode": h["returncode"]} for h in history]


@app.get("/history/{task_id}/output")
async def get_history_output(task_id: str):
    for h in history:
        if h["id"] == task_id:
            return {"output": h["output"]}
    raise HTTPException(status_code=404, detail="Command not found")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection open; can handle input if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)


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
        function connectWebSocket() {
            ws = new WebSocket("ws://" + window.location.host + "/ws");
            ws.onmessage = function(event) {
                const outputDiv = document.getElementById('output');
                outputDiv.innerHTML += event.data.replace(/\\n/g, '<br>');
                outputDiv.scrollTop = outputDiv.scrollHeight;
            };
            ws.onclose = function() {
                setTimeout(connectWebSocket, 1000);
            };
        }
        window.onload = function() {
            connectWebSocket();
            updateStatus();
            updateHistory();
        };
        function submitCommand() {
            const command = document.getElementById('command').value;
            const timeout = document.getElementById('timeout').value;
            const workingDir = document.getElementById('working-dir').value;
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            fetch('/execute', {
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
                document.getElementById('output').innerHTML = '';  // Clear for new command
                updateStatus();
                updateHistory();
            }).catch(error => {
                alert('Error: ' + error.message);
            });
        }
        function setWorkingDir() {
            const workingDir = document.getElementById('session-working-dir').value;
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) {
                alert('API Key is required');
                return;
            }
            fetch('/set-working-dir', {
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
            fetch('/status')
            .then(response => response.json())
            .then(data => {
                document.getElementById('status').innerText = `Status: ${data.status} ${data.current_command ? '- ' + data.current_command : ''} ${data.working_dir ? '(Working Dir: ' + data.working_dir + ')' : ''}`;
            });
        }
        function updateHistory() {
            fetch('/history')
            .then(response => response.json())
            .then(data => {
                const historyList = document.getElementById('history');
                historyList.innerHTML = '';
                data.forEach(item => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item';
                    li.innerHTML = `ID: ${item.id.slice(0, 8)}... | Command: ${item.command} | Working Dir: ${item.working_dir || 'N/A'} | Duration: ${item.duration.toFixed(2)}s | Return Code: ${item.returncode}
                                    <button class="btn btn-sm btn-info" onclick="viewOutput('${item.id}')">View Output</button>
                                    <button class="btn btn-sm btn-secondary" onclick="viewStatus('${item.id}')">View Status</button>`;
                    historyList.appendChild(li);
                });
            });
        }
        function viewOutput(id) {
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
                alert(`Task ID: ${data.task_id.slice(0, 8)}...\nCommand: ${data.command}\nWorking Dir: ${data.working_dir || 'N/A'}\nStatus: ${data.is_running ? 'Running' : 'Completed'}\nReturn Code: ${data.returncode ?? 'N/A'}`);
            });
        }
        setInterval(updateStatus, 2000);
        setInterval(updateHistory, 5000);
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
                    <input type="text" class="form-control" id="api-key" placeholder="Enter your API key">
                </div>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Set Session Working Directory</h5>
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
                        <input type="text" class="form-control" id="working-dir" placeholder="e.g., /path/to/dir (overrides session working dir)">
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
                <p id="status">Status: Loading...</p>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Execution History</h5>
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
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=36000)