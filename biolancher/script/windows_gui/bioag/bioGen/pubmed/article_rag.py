import sys,os

from pymed import PubMed

## pubmed library
import bioGen.pubmed.pubmed as pubmed

import re
from typing import List
import tempfile
from tqdm import tqdm
import json

from autogen_core.memory import Memory, MemoryContent, MemoryMimeType

### define logger
import logging
logger = logging.getLogger('ARTICLE_RAG')
logging.basicConfig(level=logging.DEBUG)

class PubmedDocumentIndex:
    def __init__(self, memory: Memory, chunk_size: int = 1500, article_dir: str = tempfile.gettempdir(), keyword=None) -> None:
        logger.debug(f"Initializing PubMedDocumentIndex")
        self.memory = memory
        self.chunk_size = chunk_size
        self.keyword = keyword
        self.article_dir = article_dir
        self.articles = []
        self.documents = []
        self.pubmed = None
        self.pubmed_query = {}
        self.output = None
        self.articles_text_updated = False

    def getKeyword(self) -> List[str]:
        return self.keyword
    def setKeyword(self, keyword: List[str]) -> None:
        self.keyword = keyword
    def appendKeyword(self, keyword: str) -> None:
        if keyword not in self.keyword:
            self.keyword.append(keyword)
    def initPubmed(self, mail='zhang616123@outlook.com', tool = 'pubmed_query'):
        logger.debug(f"Initializing PubMed client with tool: {tool} and email: {mail}")
        pubmed = PubMed(tool=tool, email=mail)
        self.pubmed = pubmed
    def _pubmedQueryToList(self, query_res) -> pubmed.artical:
        """Convert PubMed query results to a list of article IDs."""
        logger.debug(f"_pubmedQueryToList called with query_res: {query_res}")
        if not query_res:
            return []
        artical_list = [pubmed.artical(article.toJSON()) for article in query_res]
        return artical_list
    def _pubmedQueryListToIds(self, artical_list) -> pubmed.artical:
        """Convert PubMed query results to a list of article IDs."""
        logger.debug(f"_pubmedQueryListToIds called with artical_list: {artical_list}")
        if not artical_list or not isinstance(artical_list, list):
            return []
        return pubmed.updatePMCID(artical_list)
    def pubmedQuery(self, max_results=100) -> None:
        logger.debug(f"Pubmed query PubMed client with max_results: {max_results}")
        if not self.pubmed:
            raise ValueError("PubMed client is not initialized. Call initPubmed() first.")
        query_res = self.pubmed.query(" ".join(self.keyword), max_results=max_results)
        if not query_res:
            logger.warning("No results found for the PubMed query.")
        else:
            logger.debug(f"Found articles for the query: {' '.join(self.keyword)}")
        self.pubmed_query['query'] = self.keyword
        self.pubmed_query['query_res'] = query_res
        artical_list = self._pubmedQueryToList(query_res)
        artical_list = self._pubmedQueryListToIds(artical_list)
        self.articles = artical_list
        self.pubmed_query['articles'] = artical_list
        logger.debug(f"Pubmed query PubMed client with max_results: {max_results}")
        return None
    def updatePdf(self):
        """Update the PDF files for the articles."""
        logger.debug(f"Updating PDF files for {len(self.articles)} articles.")
        self.articles = [x.updatePdfUrl() for x in self.articles]
    def downloadPdf(self, output = None):
        if output and not self.output and output != self.output:
            logger.warning("Output directory is set but does not match the current output directory. force setting to user specific.")
            self.output = output
        if self.output is None:
            logger.warning("Output directory not set. force setting to temp directory.")
            self.output = tempfile.gettempdir() + '/pubmed_pdfs_'+ str("".join(self.keyword)).replace(' ', '_')
        logger.debug(f"Downloading PDF files to {self.output}")
        if not os.path.exists(self.output):
            os.makedirs(self.output)
        ## use tqdm to show the progress bar
        for article in tqdm(self.articles, desc="Downloading PDFs", unit="article"):
            if article.getPdfUrl():
                try:
                    article.downloadPdf(self.output)
                except Exception as e:
                    logger.error(f"Failed to download PDF for article {article.getPMCMainID()}: {e}")
            else:
                logger.warning(f"No PDF URL found for article {article.getPMCMainID()}")
    def upDatePdfText(self):
        if not self.output:
            logger.error("No output directory specified for PDF text extraction. Download pdf?")
            return None
        logger.debug(f"Updating PDF text for articles in {self.output}")
        articles = []
        for article in tqdm(self.articles, desc="Updating PDF text", unit="article"):
             articles.append(article.updateArticleText())
        self.articles = articles
        self.articles_text_updated = True

    def getArticleText(self):
        if not self.articles_text_updated:
            logger.error("Article text not updated. Call upDatePdfText() first.")
            return None
        article_text = {}
        for article in self.articles:
            pmc_id, title, first_author, last_author, pulication_Date, text = article.getPMCMainID(), article.getTitle(), article.getFisrtauthor(), article.getLastauthor(), article.getPulicationDate(), article.getArticleText()
            abstract = article.getAbstract()
            article_text[title] = {
                'pmc_id': pmc_id,
                'title': title,
                'first_author': first_author,
                'last_author': last_author,
                'publication_date': pulication_Date,
                'abstract': abstract,
                'text': text
            }
        return article_text
    
    def getArticleMarkdownText(self):
        if not self.articles_text_updated:
            logger.error("Article text not updated. Call upDatePdfText() first.")
            return None

        markdown_parts = ["# Articles\n\n"]

        for article in self.articles:
            pmc_id = article.getPMCMainID()
            title = article.getTitle()
            first_author = article.getFisrtauthor()
            last_author = article.getLastauthor()
            publication_date = article.getPulicationDate()
            text = article.getArticleText()
            abstract = article.getAbstract()

            # 处理可能为 None 的字段
            abstract = abstract if abstract else "No abstract available."
            text = text if text else "No full text available."

            md_lines = [
                f"## {title}",
                "",
                f"**PMC ID:** {pmc_id}  ",
                f"**First Author:** {first_author}  ",
                f"**Last Author:** {last_author}  ",
                f"**Publication Date:** {publication_date}",
                "",
                "### Abstract",
                abstract,
                "",
                "### Full Text",
                "",
                text,
                "",
                "---",
                "",
            ]
            md_part = "\n".join(md_lines)

            markdown_parts.append(md_part)

        return "".join(markdown_parts)

    ## memory database
    def _split_text(self, text: str) -> List[str]:
        """Split text into fixed-size chunks."""
        chunks: list[str] = []
        # Just split text into fixed-size chunks
        for i in range(0, len(text), self.chunk_size):
            chunk = text[i : i + self.chunk_size]
            chunks.append(chunk.strip())
        return chunks
    async def addMemory(self, content: dict = None, multiple: bool = True):
        if not content:
            if not self.articles_text_updated:
                logger.error("Article text not updated. Call upDatePdfText() first. or provide content.")
            content = self.getArticleText()
        if not multiple:
            content = {content}
        total_chunk = 0
        for k, v in content.items():
            logger.debug(f"Adding memory for article {k}")
            if not isinstance(v, dict):
                logger.error(f"Content for {k} is not a dictionary. Skipping.")
                continue
            text = v.get('text', '')
            if not text:
                logger.warning(f"No text found for article {k}. use abstract instead, Skipping.")
                text = v.get('title', '')
                #continue
            mime_type = MemoryMimeType.TEXT
            chunks = self._split_text(text)
            for i, chunk in enumerate(chunks):
                memory_content = MemoryContent(
                    content=text,
                    mime_type=mime_type,
                    metadata={
                        'pmc_id': str(v.get('pmc_id', '')),
                        'title': str(v.get('title', '')),
                        'first_author': " ".join(v.get('first_author', '')),
                        'last_author': " ".join(v.get('last_author', '')),
                        #'publication_date': str(v.get('publication_date', '')),
                        #'abstract': str(v.get('abstract', '')),
                        'chunk_index': i,
                    }
                )
                await self.memory.add(memory_content)
                total_chunk += 1
        logger.debug(f"Added {total_chunk} chunks to memory.")
        return None
    def getMemory(self):
        """Retrieve all memory contents."""
        logger.debug("Retrieving all memory contents.")
        return self.memory

    def __str__(self):
        class_summary = f"PubmedDocumentIndex(keyword={self.keyword}, articles={len(self.articles)})"
        return class_summary


import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig, \
    SentenceTransformerEmbeddingFunctionConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient

import asyncio

import chromadb
from chromadb import Settings

def pubmed_search_to_rag(keyword: str, chroma_db: ChromaDBVectorMemory, max_results: int = 50, content = False):
    """
    Perform a PubMed search and add the results to the RAG memory.
    """
    pbObj = PubmedDocumentIndex(
        memory=chroma_db,
        chunk_size=1500,
        article_dir=tempfile.gettempdir(),
        keyword=[keyword]
    )
    pbObj.initPubmed(tool='pubmed.query')
    pbObj.pubmedQuery(max_results=max_results)
    pbObj.updatePdf()
    pbObj.downloadPdf()
    pbObj.upDatePdfText()
    sys.stderr.write('PUBMED RAG: ==============Update Pdf Text Finished==============\n')
    #asyncio.run(pbObj.addMemory())
    pbObj.addMemory()
    sys.stderr.write('PUBMED RAG: ==============Update Memory Text Finished==============\n')
    article_text = pbObj.getArticleMarkdownText()
    chroma_db = pbObj.getMemory()
    if content: 
        return article_text
    return chroma_db

if __name__ == "__main__":
    keyword = 'MYC'
    ## create a PubmedDocumentIndex instance
    rag_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="autogen_docs",
            persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen"),
            k=3,  # Return top 3 results
            score_threshold=0.4,  # Minimum similarity score
            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
                model_name="all-MiniLM-L6-v2"  # Use default model for testing
            ),
            #embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
            #    model_name="paraphrase-multilingual-mpnet-base-v2"
            #),
        )
    )
    asyncio.run(rag_memory.clear())
    pbObj = PubmedDocumentIndex(
        memory=rag_memory,
        chunk_size=1500,
        article_dir=tempfile.gettempdir(),
        keyword=[keyword]
    )
    pbObj.initPubmed(tool='pubmed.query')
    pbObj.pubmedQuery(max_results=10)
    pbObj.updatePdf()
    pbObj.downloadPdf()
    pbObj.upDatePdfText()
    asyncio.run(pbObj.addMemory())
    article_text = pbObj.getArticleText()

    ## json dump the article text for debug
    with open('/mnt/e/software/bioGen/debug/article_text.json', 'w') as f:
        json.dump(article_text, f, indent=4)

    print(article_text)
    print(pbObj)

    custom_model_client = OpenAIChatCompletionClient(
        model="grok-3-mini",
        base_url="https://api.x.ai/v1/",
        api_key="xai-BOIfL6K4hZYigWTQ6U6Uaoumy383e34dohxZAjYllq2HfOL8ECXQoGbK5g3EZ2zKEaqX1DwsgDJdrNbd",
        # Replace with actual API key
        # api_key="xai-wruPEbZKjFIuOOjNcph3GcLSnFLOHxIrFhjZHrSbAoyNUVB4MOYTrw4XEHQuizCSFZ42ibiKEcOM8J5u",
        model_info={
            "vision": True,
            "function_calling": True,  # Enable function calling to support tool usage
            "json_output": True,
            "family": 'gpt-4o',
            "structured_output": True,
            "multiple_system_messages": True
        },
    )

    chroma_user_memory = pbObj.getMemory()
    print(chroma_user_memory.query('MYC'))
    assistant_agent = AssistantAgent(
                    name="rag_assistant", model_client=custom_model_client, memory=[rag_memory]
    )

    stream = assistant_agent.run_stream(task="You are a helpful AI assistant. Solve tasks user query base on your memory. You are a precise assistant. \
                        Always base your answer ONLY on the provided MEMORY.If the MEMORY is insufficient, say \"I don't know\". \
                        Before answering, repeat the exact MEMORY you are using. After answering, \
                        list the IDs of the context chunks you used. Reply with TERMINATE when the task has been completed.\n \
                        Question: What is the MYC",)
    asyncio.run(Console(stream))

    #asyncio.run(custom_model_client.close())
    #asyncio.run(chroma_user_memory.close())