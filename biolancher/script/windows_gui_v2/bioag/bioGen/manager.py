import asyncio

from autogen.fast_depends import Provider
from autogen_core import CancellationToken

import bioGen.biogen as bg
from typing import AsyncGenerator, Union, Optional
import time
import json
from pathlib import Path
from autogen_agentchat.messages import ChatMessage

from typing import Any, List, Literal, Optional
from pydantic import BaseModel
from pydantic.dataclasses import dataclass
from autogen_agentchat.base import TaskResult


@dataclass
class ModelConfig:
    model: str
    model_type: Literal["OpenAIChatCompletionClient"]


@dataclass
class ToolConfig:
    name: str
    description: str
    content: str


@dataclass
class AgentConfig:
    name: str
    agent_type: Literal["AssistantAgent", "CodingAssistantAgent"]
    system_message: Optional[str] = None
    model_client: Optional[ModelConfig] = None
    tools: Optional[List[ToolConfig]] = None
    description: Optional[str] = None


@dataclass
class TerminationConfig:
    termination_type: Literal["MaxMessageTermination",
                              "StopMessageTermination", "TextMentionTermination"]
    max_messages: Optional[int] = None
    text: Optional[str] = None


@dataclass
class TeamConfig:
    name: str
    participants: List[AgentConfig]
    team_type: Literal["RoundRobinGroupChat", "SelectorGroupChat"]
    model_client: Optional[ModelConfig] = None
    termination_condition: Optional[TerminationConfig] = None


class TeamResult(BaseModel):
    task_result: TaskResult
    usage: str
    duration: float

class TeamManager:
    def __init__(self, agent) -> None:
        self.provider = Provider()
        self.agent = agent

    async def load_team_config(self, config_path: Union[str, Path]) -> TeamConfig:
        return self.agent

    async def run_stream(
        self,
        task: str = "",
        team_config: Optional[Union[TeamConfig, str, Path]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> AsyncGenerator[Union[ChatMessage, TaskResult], None]:
        """Stream the team's execution results with optional JSON config loading"""
        start_time = time.time()

        try:
            # Use provider to create team from config
            team = self.agent

            # Check if team supports streaming
            if not hasattr(team, 'run_stream'):
                raise NotImplementedError("Team does not support streaming")

            stream = team.run_stream(
                task=task,
                cancellation_token=cancellation_token
            )

            async for message in stream:
                if cancellation_token and cancellation_token.is_cancelled():
                    break

                if isinstance(message, TaskResult):
                    yield TeamResult(
                        task_result=message,
                        usage="",  # TODO: Implement token usage parsing
                        duration=time.time() - start_time
                    )
                else:
                    yield message

        except Exception as e:
            raise e

    async def run(
        self,
        task: str = '',
        team_config: Optional[Union[TeamConfig, str, Path]] = None,
        cancellation_token: Optional[CancellationToken] = None
    ) -> TeamResult:
        """Non-streaming run method with optional JSON config loading"""
        start_time = time.time()

        try:
            if isinstance(team_config, (str, Path)):
                team_config = await self.load_team_config(team_config)
            elif team_config is None:
                # Load default team config if none provided
                team_config = await self.load_team_config("notebooks/default_team.json")

            # Use provider to create team from config
            team = self.agent

            result = await team.run(
                task=task,
                cancellation_token=cancellation_token
            )

            return TeamResult(
                task_result=result,
                usage="",  # TODO: Implement token usage parsing
                duration=time.time() - start_time
            )

        except Exception as e:
            raise e

if __name__ == "__main__":
    work_team = TeamManager(bg.selector_team)
    asyncio.run(work_team.run())