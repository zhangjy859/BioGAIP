API Documentation for Command Execution Server
This document provides comprehensive API documentation for the FastAPI-based server application designed for managing projects, executing shell commands, setting working directories, retrieving statuses, histories, and real-time outputs via WebSocket. The server requires an API key for protected endpoints, which is checked via the x-api-key header. If no API_KEY environment variable is set, a random key is generated, set in the environment, and printed to the console.
Base URL

Base URL: http://localhost:8000 (or the deployed host/port)

Authentication

All POST endpoints and some GET endpoints require authentication via the x-api-key header.
Header: x-api-key: <your_api_key>
If the key is invalid, a 401 Unauthorized response is returned with {"detail": "Invalid API Key"}.

Error Handling

Common errors include:
401: Invalid API Key
404: Project or Task not found
409: Command already running in the project
400: Invalid working directory


Responses follow standard FastAPI error formats, e.g., {"detail": "Error message"}.

Endpoints
1. Create a New Project

Method: POST
Path: /projects
Description: Creates a new project and returns its unique ID. Each project manages its own commands, history, and working directory.
Headers:
x-api-key: Required string


Request Body: None
Response:
Status: 200 OK
Body: {"project_id": "<uuid_string>"}


Example Request (cURL):curl -X POST "http://localhost:8000/projects" -H "x-api-key: your_api_key"


Example Response:{"project_id": "123e4567-e89b-12d3-a456-426614174000"}



2. Execute a Command in a Project

Method: POST
Path: /projects/{project_id}/execute
Description: Executes a shell command in the specified project. Only one command can run per project at a time. Updates the global latest task for real-time output tracking.
Path Parameters:
project_id: Required string (UUID of the project)


Headers:
x-api-key: Required string


Request Body (JSON, CommandRequest model):
command: Required string (the shell command to execute)
timeout: Optional float (timeout in seconds; if exceeded, kills the process)
working_dir: Optional string (overrides project working directory if provided)


Response:
Status: 200 OK
Body: {"message": "Command started", "id": "<task_uuid>"}


Errors:
409: If a command is already running


Example Request (cURL):curl -X POST "http://localhost:8000/projects/123e4567-e89b-12d3-a456-426614174000/execute" \
-H "Content-Type: application/json" -H "x-api-key: your_api_key" \
-d '{"command": "echo Hello World", "timeout": 10}'


Example Response:{"message": "Command started", "id": "98765432-1234-5678-9012-345678901234"}



3. Set Working Directory for a Project

Method: POST
Path: /projects/{project_id}/set-working-dir
Description: Sets the default working directory for the project. Must be a valid directory path.
Path Parameters:
project_id: Required string (UUID of the project)


Headers:
x-api-key: Required string


Request Body (JSON, WorkingDirRequest model):
working_dir: Required string (valid directory path)


Response:
Status: 200 OK
Body: {"message": "Project working directory set to <path>"}


Errors:
400: Invalid working directory


Example Request (cURL):curl -X POST "http://localhost:8000/projects/123e4567-e89b-12d3-a456-426614174000/set-working-dir" \
-H "Content-Type: application/json" -H "x-api-key: your_api_key" \
-d '{"working_dir": "/path/to/dir"}'


Example Response:{"message": "Project working directory set to /path/to/dir"}



4. Get Project Status

Method: GET
Path: /projects/{project_id}/status
Description: Retrieves the current status of the project, including if a command is running and the working directory.
Path Parameters:
project_id: Required string (UUID of the project)


Headers: None (no auth required)
Request Body: None
Response:
Status: 200 OK
Body: {"is_running": bool, "current_command": string or null, "status": "running" or "idle", "working_dir": string or null}


Example Request (cURL):curl -X GET "http://localhost:8000/projects/123e4567-e89b-12d3-a456-426614174000/status"


Example Response:{"is_running": true, "current_command": "echo Hello World", "status": "running", "working_dir": "/path/to/dir"}



5. Get Task Status

Method: GET
Path: /status/{task_id}
Description: Retrieves the status of a specific task (command), including if it's running and its return code (if completed).
Path Parameters:
task_id: Required string (UUID of the task)


Headers: None (no auth required)
Request Body: None
Response:
Status: 200 OK
Body: {"task_id": string, "project_id": string, "is_running": bool, "command": string, "working_dir": string or null, "returncode": int or null}


Example Request (cURL):curl -X GET "http://localhost:8000/status/98765432-1234-5678-9012-345678901234"


Example Response:{"task_id": "98765432-1234-5678-9012-345678901234", "project_id": "123e4567-e89b-12d3-a456-426614174000", "is_running": false, "command": "echo Hello World", "working_dir": "/path/to/dir", "returncode": 0}



6. Get Project History

Method: GET
Path: /projects/{project_id}/history
Description: Retrieves the execution history of commands in the project (without full outputs for efficiency).
Path Parameters:
project_id: Required string (UUID of the project)


Headers: None (no auth required)
Request Body: None
Response:
Status: 200 OK
Body: Array of objects: [{"id": string, "command": string, "working_dir": string or null, "duration": float, "returncode": int}]


Example Request (cURL):curl -X GET "http://localhost:8000/projects/123e4567-e89b-12d3-a456-426614174000/history"


Example Response:[{"id": "98765432-1234-5678-9012-345678901234", "command": "echo Hello World", "working_dir": "/path/to/dir", "duration": 0.5, "returncode": 0}]



7. Get Task Output from History

Method: GET
Path: /history/{task_id}/output
Description: Retrieves the full output of a completed task from history.
Path Parameters:
task_id: Required string (UUID of the task)


Headers: None (no auth required)
Request Body: None
Response:
Status: 200 OK
Body: {"output": string}


Example Request (cURL):curl -X GET "http://localhost:8000/history/98765432-1234-5678-9012-345678901234/output"


Example Response:{"output": "Hello World\n"}



8. WebSocket for Real-Time Output

Method: WebSocket
Path: /ws/{project_id}
Description: Establishes a WebSocket connection for real-time console output of the latest running command in the project. Broadcasts updates only for the globally latest task. Sends full current output on each update, "CLEAR_OUTPUT" on new command start, "COMMAND_COMPLETE" on completion.
Path Parameters:
project_id: Required string (UUID of the project)


Headers: None (no auth required for WebSocket)
Messages:
Client sends: "REQUEST_CURRENT_OUTPUT" to request the current output.
Server sends: Full output string (replaces previous content), "CLEAR_OUTPUT", or "COMMAND_COMPLETE".


Example Usage (JavaScript):const ws = new WebSocket("ws://localhost:8000/ws/123e4567-e89b-12d3-a456-426614174000");
ws.onopen = () => ws.send("REQUEST_CURRENT_OUTPUT");
ws.onmessage = (event) => {
  if (event.data === "CLEAR_OUTPUT" || event.data === "COMMAND_COMPLETE") {
    consoleOutput.innerHTML = '';
  } else {
    consoleOutput.innerHTML = event.data.replace(/\n/g, '<br>');
  }
};



9. Root Endpoint (Web Panel)

Method: GET
Path: /
Description: Serves the HTML-based visualization panel for interacting with the API (submit commands, view history, live output).
Headers: None
Request Body: None
Response:
Status: 200 OK
Content-Type: text/html
Body: HTML content for the panel


Example Request (cURL):curl -X GET "http://localhost:8000/"


Note: This is a frontend interface; access via browser for full functionality.

Models

CommandRequest:

command: str (required)
timeout: float (optional)
working_dir: str (optional)


WorkingDirRequest:

working_dir: str (required)



Additional Notes

Real-Time Output: The WebSocket broadcasts the full current output on each line update for the latest task, allowing the client to clear and redraw the screen.
Output Limiting: Outputs are capped at 1000 lines in memory to prevent overflow.
History Storage: Command histories are saved to JSON files in {log_dir}/cmd_history/{project_id}.json, with large outputs truncated.
Environment Variables:
API_KEY: API authentication key (generated if missing).
LOG_DIR: Directory for history logs (defaults to current working directory).


Dependencies: Requires FastAPI, Uvicorn, Pydantic, and standard Python libraries. Run with uvicorn for production.

For interactive docs, access /docs (Swagger) or /redoc when the server is running, as FastAPI auto-generates OpenAPI schema.