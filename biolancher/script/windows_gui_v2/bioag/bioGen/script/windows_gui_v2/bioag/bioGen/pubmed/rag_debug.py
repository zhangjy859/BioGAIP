import re
import sys
from typing import List

import aiofiles
import aiohttp
from autogen_core.memory import Memory, MemoryContent, MemoryMimeType
import asyncio,os

os.environ["HTTPS_PROXY"] = "http://172.20.0.1:1083"
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient

custom_model_client = OpenAIChatCompletionClient(
    model="grok-3-mini",
    base_url="https://api.x.ai/v1/",
    api_key="xai-...",  # Replace with actual API key
    #api_key="xai-...",
    model_info={
        "vision": True,
        "function_calling": True,  # Enable function calling to support tool usage
        "json_output": True,
        "family": 'gpt-4o',
        "structured_output": True,
        "multiple_system_messages": True,
    },
)

class SimpleDocumentIndexer:
    """Basic document indexer for AutoGen Memory."""

    def __init__(self, memory: Memory, chunk_size: int = 1500) -> None:
        self.memory = memory
        self.chunk_size = chunk_size

    async def _fetch_content(self, source: str) -> str:
        """Fetch content from URL or file."""
        if source.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async with session.get(source) as response:
                    return await response.text()
        else:
            async with aiofiles.open(source, "r", encoding="utf-8") as f:
                return await f.read()

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        text = re.sub(r"<[^>]*>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _split_text(self, text: str) -> List[str]:
        """Split text into fixed-size chunks."""
        chunks: list[str] = []
        # Just split text into fixed-size chunks
        for i in range(0, len(text), self.chunk_size):
            chunk = text[i : i + self.chunk_size]
            chunks.append(chunk.strip())
        return chunks

    async def index_documents(self, sources: List[str]) -> int:
        """Index documents into memory."""
        total_chunks = 0

        for source in sources:
            sys.stderr.write(f"Indexing {source}\n")
            try:
                content = await self._fetch_content(source)

                # Strip HTML if content appears to be HTML
                if "<" in content and ">" in content:
                    content = self._strip_html(content)

                chunks = self._split_text(content)

                for i, chunk in enumerate(chunks):
                    await self.memory.add(
                        MemoryContent(
                            content=chunk, mime_type=MemoryMimeType.TEXT, metadata={"source": source, "chunk_index": i}
                        )
                    )

                total_chunks += len(chunks)

            except Exception as e:
                print(f"Error indexing {source}: {str(e)}")

        return total_chunks


import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient

# Initialize vector memory

rag_memory = ChromaDBVectorMemory(
    config=PersistentChromaDBVectorMemoryConfig(
        collection_name="autogen_docs",
        persistence_path=os.path.join(str(Path.home()), ".debug.chromadb_autogen"),
        k=3,  # Return top 3 results
        score_threshold=0.4,  # Minimum similarity score
    )
)



# Index AutoGen documentation
sys.stderr.write('Indexing AutoGen documentation...\n')
async def index_autogen_docs() -> None:
    indexer = SimpleDocumentIndexer(memory=rag_memory)
    sources = [
        "https://ghfast.top/https://raw.githubusercontent.com/microsoft/autogen/main/README.md",
    ]
    chunks: int = await indexer.index_documents(sources)
    print(f"Indexed {chunks} chunks from {len(sources)} AutoGen documents")


asyncio.run(index_autogen_docs())

# Create our RAG assistant agent
rag_assistant = AssistantAgent(
    name="rag_assistant", model_client=custom_model_client, memory=[rag_memory]
)

# Ask questions about AutoGen
stream = rag_assistant.run_stream(task="Solve tasks user query base on your memory. You are a precise assistant. \
                        Always base your answer ONLY on the provided MEMORY.If the MEMORY is insufficient, say \"I don't know\". \
                        Before answering, repeat the exact MEMORY you are using. After answering, \
                        list the IDs of the context chunks you used. Reply with TERMINATE when the task has been completed.\n \
                        What is AgentChat?")
asyncio.run(Console(stream))

# Remember to close the memory when done
asyncio.run(rag_memory.close())