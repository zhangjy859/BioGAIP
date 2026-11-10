import sys
import asyncio
from asyncio import sleep, Queue, Event
from collections.abc import AsyncGenerator

from autogen.messages.agent_messages import ToolCallMessage
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, List, Union
import logging
import os
import uuid
import datetime
import traceback
from pathlib import Path

# Import your team manager components
from autogen_agentchat import EVENT_LOGGER_NAME
from autogen_agentchat.messages import ChatMessage, TextMessage, UserInputRequestedEvent, ThoughtEvent
from autogen_core import CancellationToken
from bioGen.manager import TeamManager
from bioGen.datamodel import TeamResult, TaskResult
import bioGen.biogen as bg


class GenerateWebRequest(BaseModel):
    prompt: str
    history: Optional[str] = ""
    session_id: str


class UserInputMessage(BaseModel):
    type: str = "user_input"
    content: str


class ConnectionManager:
    def __init__(self):
        # 存放WebSocket连接
        self.active_connections: Dict[str, WebSocket] = {}
        # 存放用于传递用户输入的队列
        self.user_input_queues: Dict[str, Queue] = {}
        # 存放用于通知需要输入的事件
        self.user_input_requests: Dict[str, Event] = {}
        # 存放正在运行的agent任务
        self.agent_tasks: Dict[str, asyncio.Task] = {}

    async def create_session(self) -> str:
        """创建新会话ID"""
        return str(uuid.uuid4())

    async def connect(self, session_id: str, websocket: WebSocket):
        """连接WebSocket并为会话初始化资源"""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.user_input_queues[session_id] = Queue()
        self.user_input_requests[session_id] = Event()
        logging.info(f"WebSocket connected for session: {session_id}")

    async def disconnect(self, session_id: str):
        """断开WebSocket连接并清理资源"""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        if session_id in self.user_input_queues:
            del self.user_input_queues[session_id]
        if session_id in self.user_input_requests:
            del self.user_input_requests[session_id]
        # 取消与此会话相关的任何正在运行的agent任务
        if session_id in self.agent_tasks and not self.agent_tasks[session_id].done():
            self.agent_tasks[session_id].cancel()
            del self.agent_tasks[session_id]
        logging.info(f"WebSocket disconnected and resources cleaned for session: {session_id}")

    def get_connection(self, session_id: str) -> Optional[WebSocket]:
        """按会话ID获取WebSocket连接"""
        return self.active_connections.get(session_id)


# Initialize FastAPI
app = FastAPI()

# Create API router
api = FastAPI(root_path="/api")

# Add CORS middleware to the router as well (or just use the app one)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize managers
connection_manager = ConnectionManager()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(EVENT_LOGGER_NAME)
logger.setLevel(logging.INFO)


@api.post("/create_session")
async def create_session() -> Dict:
    """为聊天交互创建新会话"""
    session_id = await connection_manager.create_session()
    logger.info(f"Created new session: {session_id}")
    return {"session_id": session_id}


@api.websocket("/ws/logs/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    处理WebSocket连接。这是唯一的读取器。
    它监听来自客户端的消息，并将其分派到正确的地方。
    """
    await connection_manager.connect(session_id, websocket)
    input_request_event = connection_manager.user_input_requests.get(session_id)
    input_queue = connection_manager.user_input_queues.get(session_id)

    if not input_request_event or not input_queue:
        logger.error(f"Session {session_id} not properly initialized.")
        await websocket.close(code=1011, reason="Session initialization failed")
        return

    try:
        while True:
            # 始终使用 receive_json 来统一消息格式
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "ThoughtEvent":
                pass
            if message_type == "user_input":
                # 检查agent是否正在等待输入
                if input_request_event.is_set():
                    await input_queue.put(data.get("content", ""))
                else:
                    logger.warning(f"Received user input for session {session_id}, but no agent is waiting.")

            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                logger.warning(f"Received unknown message type: {message_type}")

    except WebSocketDisconnect:
        await connection_manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {str(e)}")
        await connection_manager.disconnect(session_id)


async def run_agent_task(session_id: str, prompt: str):
    """
    在后台运行autogen任务的函数。
    """
    websocket = connection_manager.get_connection(session_id)
    input_request_event = connection_manager.user_input_requests.get(session_id)
    input_queue = connection_manager.user_input_queues.get(session_id)

    if not all([websocket, input_request_event, input_queue]):
        logger.error(f"Cannot start agent task: session {session_id} is not ready.")
        return

    async def _user_input(prompt_text: str, cancellation_token: CancellationToken | None) -> str:
        """
        新的_user_input函数，使用Event和Queue与websocket_endpoint通信。
        """
        # 1. 发送一个事件到前端，告诉它需要用户输入了
        await websocket.send_json({
            "type": "UserInputRequest",
            "content": prompt_text,
            "timestamp": str(datetime.datetime.now())
        })

        # 2. 设置Event，通知websocket_endpoint我们正在等待输入
        input_request_event.set()
        logger.info(f"Agent is now waiting for user input for session {session_id}.")

        try:
            # 3. 从队列中等待用户输入
            user_response = await input_queue.get()
            logger.info(f"Agent received user input for session {session_id}.")
            return user_response
        finally:
            # 4. 清理Event，为下一次输入请求做准备
            input_request_event.clear()
            input_queue.task_done()

    # 注意：TeamManager和team现在在这里初始化，以捕获正确的闭包
    team_manager = TeamManager(bg.get_team(_user_input))

    try:
        async for message in team_manager.run_stream(task=prompt, cancellation_token=None):
            try:
                logger.info(f"Session {session_id}: {message}")
                # 你的消息处理逻辑保持不变
                if isinstance(message, (UserInputRequestedEvent)):
                    # 这个事件现在由 _user_input 内部处理，但我们仍然可以记录它
                    logger.info(f"Event: UserInputRequested for session {session_id}")
                    pass
                elif isinstance(message, TextMessage):
                    await websocket.send_json({
                        "type": "message",
                        "content": message.content,
                        "source": message.source if hasattr(message, 'source') else "system",
                        "timestamp": str(datetime.datetime.now())
                    })
                elif isinstance(message, TeamResult):
                    await websocket.send_json({
                        "type": "result",
                        "content": str(message.task_result.messages[-1].content) if hasattr(message.task_result,
                                                                                            'messages') else str(
                            message),
                        "source": "task_result",
                        "timestamp": str(datetime.datetime.now())
                    })
                elif isinstance(message, ThoughtEvent):
                    pass
                    await websocket.send_json({'type': 'message', 'content': message.content, 'source': message.source, 'timestamp': str(datetime.datetime.now())})
            except Exception as e:
                logger.error(f"Error sending message for session {session_id}: {str(e)}")
                raise

        # 任务完成
        await websocket.send_json({
            "type": "TerminationEvent",
            "content": "Stream completed",
            "timestamp": str(datetime.datetime.now())
        })

    except asyncio.CancelledError:
        logger.info(f"Agent task for session {session_id} was cancelled.")
    except Exception as e:
        logger.error(f"Error in agent task for session {session_id}: {str(e)}")
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "ErrorEvent",
                "content": str(e),
                "timestamp": str(datetime.datetime.now())
            })
        except Exception:
            logger.error("Failed to send error event through WebSocket.")
    finally:
        # 任务结束后，从管理器中移除
        if session_id in connection_manager.agent_tasks:
            del connection_manager.agent_tasks[session_id]


@api.post("/generate")
async def generate(req: GenerateWebRequest):
    """
    通过创建后台任务来启动流式响应。
    """
    logger.info(f"Generate request received for session: {req.session_id}")
    session_id = req.session_id

    if not session_id or not connection_manager.get_connection(session_id):
        raise HTTPException(status_code=404, detail="Session not found or WebSocket not connected.")

    # 如果该会话已有任务在运行，则阻止新的任务启动
    if session_id in connection_manager.agent_tasks and not connection_manager.agent_tasks[session_id].done():
        raise HTTPException(status_code=409, detail="An agent task is already running for this session.")

    # 创建并存储后台任务
    task = asyncio.create_task(run_agent_task(session_id, req.prompt))
    connection_manager.agent_tasks[session_id] = task

    return JSONResponse(
        status_code=202,  # 202 Accepted 表示请求已被接受处理，但尚未完成
        content={"status": True, "message": "Agent task started.", "session_id": session_id}
    )


# 挂载API路由
app.mount("/api", api)


@app.get("/")
async def root():
    return {"message": "API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)