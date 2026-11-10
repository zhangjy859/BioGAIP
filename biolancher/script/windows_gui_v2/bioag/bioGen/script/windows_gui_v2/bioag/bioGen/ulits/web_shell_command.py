import os
import signal
import time
import threading
import queue
import subprocess
import asyncio
from typing import Optional, List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI()

# Global state
is_running: bool = False
current_command: str = ""
current_output: List[str] = []
history: List[Dict] = []
output_queue: queue.Queue = queue.Queue()
manager = None  # Will be initialized later
loop = None  # Will be set in startup


class CommandRequest(BaseModel):
    command: str
    timeout: Optional[float] = None


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


def run_shell_command(command: str, timeout: Optional[float] = None, output_queue: Optional[queue.Queue] = None) -> int:
    """
    Executes a shell command, sends stdout and stderr to output_queue in real-time,
    and kills the process tree if timeout is exceeded.

    :param command: The shell command to execute (str).
    :param timeout: Optional timeout in seconds (int or float). If exceeded, kill the process tree.
    :param output_queue: Optional queue to put output lines into.
    :return: Return code of the process.
    """
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid  # Create a new process group for killing the tree
    )

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


@app.post("/execute")
async def execute_command(request: CommandRequest):
    global is_running, current_command, current_output, output_queue
    if is_running:
        raise HTTPException(status_code=409, detail="A command is already running.")

    current_command = request.command
    current_output = []
    output_queue = queue.Queue()  # New queue for this command
    is_running = True

    # Start output processing thread
    output_thread = threading.Thread(target=process_output)
    output_thread.start()

    start_time = time.time()
    command_id = len(history) + 1

    def run_command():
        global is_running
        returncode = run_shell_command(request.command, request.timeout, output_queue)
        end_time = time.time()
        is_running = False
        full_output = ''.join(current_output)
        history.append({
            "id": command_id,
            "command": request.command,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
            "returncode": returncode,
            "output": full_output
        })

    # Start command execution in background thread
    command_thread = threading.Thread(target=run_command)
    command_thread.start()

    return {"message": "Command started", "id": command_id}


@app.get("/status")
async def get_status():
    return {
        "is_running": is_running,
        "current_command": current_command if is_running else None,
        "status": "running" if is_running else "idle"
    }


@app.get("/history")
async def get_history():
    # Return history without full output to keep response light
    return [{"id": h["id"], "command": h["command"], "duration": h["duration"], "returncode": h["returncode"]} for h in
            history]


@app.get("/history/{command_id}/output")
async def get_history_output(command_id: int):
    for h in history:
        if h["id"] == command_id:
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
            fetch('/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: command, timeout: timeout ? parseFloat(timeout) : null})
            }).then(response => response.json())
            .then(data => {
                alert(data.message);
                document.getElementById('output').innerHTML = '';  // Clear for new command
                updateStatus();
                updateHistory();
            });
        }
        function updateStatus() {
            fetch('/status')
            .then(response => response.json())
            .then(data => {
                document.getElementById('status').innerText = `Status: ${data.status} ${data.current_command ? '- ' + data.current_command : ''}`;
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
                    li.innerHTML = `ID: ${item.id} | Command: ${item.command} | Duration: ${item.duration.toFixed(2)}s | Return Code: ${item.returncode}
                                    <button class="btn btn-sm btn-info" onclick="viewOutput(${item.id})">View Output</button>`;
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
        setInterval(updateStatus, 2000);
        setInterval(updateHistory, 5000);
    </script>
</head>
<body>
    <div class="container mt-5">
        <h1 class="mb-4">Command Execution Panel</h1>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Submit Command</h5>
                <form>
                    <div class="mb-3">
                        <label for="command" class="form-label">Command</label>
                        <input type="text" class="form-control" id="command" placeholder="e.g., echo Hello World">
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
    uvicorn.run(app, host="0.0.0.0", port=38000)