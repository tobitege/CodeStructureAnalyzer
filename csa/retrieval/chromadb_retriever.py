import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)


class ChromaDBAnalysisRetriever:
    """
    Retriever for querying analysis data from ChromaDB.

    This class provides methods to search and retrieve code analysis data
    stored in a ChromaDB vector database by the ChromaDBAnalysisReporter.
    """

    def __init__(self, db_path: str = "data/chroma"):
        """
        Initialize the ChromaDB retriever.

        Args:
            db_path: Path to the ChromaDB database directory
        """
        self.db_path = db_path
        self.client: Optional[chromadb.PersistentClient] = None
        self.collections: Dict[str, chromadb.Collection] = {}
        self.embedding_function = None

        # Collection names we expect to find
        self.expected_collections = [
            "file_summaries",
            "classes",
            "functions",
            "dependencies",
            "metadata"
        ]

    def connect(self) -> bool:
        """
        Connect to the existing ChromaDB collections.

        Returns:
            Boolean indicating whether connection was successful
        """
        if not os.path.exists(self.db_path):
            logger.error(f"ChromaDB path not found: {self.db_path}")
            return False

        try:
            # Initialize ChromaDB client
            self.client = chromadb.PersistentClient(
                path=self.db_path,
                settings=Settings(anonymized_telemetry=False)
            )

            # Use sentence-transformers for embeddings (same as reporter)
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            # Get existing collections
            for collection_name in self.expected_collections:
                try:
                    collection = self.client.get_collection(
                        name=collection_name,
                        embedding_function=self.embedding_function
                    )
                    self.collections[collection_name] = collection
                    logger.debug(f"Connected to collection: {collection_name}")
                except Exception as e:
                    logger.warning(f"Collection {collection_name} not found: {str(e)}")

            if not self.collections:
                logger.error("No collections found in the database")
                return False

            # Get database info from metadata
            if "metadata" in self.collections:
                try:
                    info = self.collections["metadata"].get(ids=["project_info"])
                    if info and info["metadatas"]:
                        metadata = info["metadatas"][0]
                        source_dir = metadata.get("source_dir", "Unknown")
                        file_count = metadata.get("file_count", 0)
                        analysis_date = metadata.get("analysis_date", "Unknown")
                        logger.info(f"Connected to analysis database for {source_dir}")
                        logger.info(f"Contains {file_count} files, analyzed on {analysis_date}")
                except Exception as e:
                    logger.warning(f"Error reading metadata: {str(e)}")

            return True

        except Exception as e:
            logger.error(f"Error connecting to ChromaDB: {str(e)}")
            return False

    def search_codebase(
        self,
        query: str,
        n_results: int = 10,
        collection: str = "all",
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search across specified or all collections.

        Args:
            query: Search query
            n_results: Maximum number of results to return
            collection: Collection name to search or "all" for all collections
            filters: Dictionary of metadata filters

        Returns:
            List of search results with metadata
        """
        if self.client is None:
            if not self.connect():
                return []

        results = []

        # Determine which collections to search
        search_collections = []
        if collection == "all":
            search_collections = list(self.collections.keys())
            # Don't search metadata by default
            if "metadata" in search_collections:
                search_collections.remove("metadata")
        elif collection in self.collections:
            search_collections = [collection]
        else:
            logger.error(f"Collection {collection} not found")
            return []

        # Convert filters to ChromaDB where clauses
        where_clause = None
        if filters:
            where_clause = {}
            for key, value in filters.items():
                where_clause[key] = value

        # Search each collection
        for coll_name in search_collections:
            try:
                # Skip invalid collections
                if coll_name not in self.collections:
                    logger.warning(f"Collection {coll_name} not found, skipping")
                    continue

                coll_instance = self.collections[coll_name]

                # Adjust n_results based on number of collections
                per_collection_results = min(n_results, 20)

                # Search the collection
                query_results = coll_instance.query(
                    query_texts=[query],
                    n_results=per_collection_results,
                    where=where_clause
                )

                # Process results
                if query_results and all(key in query_results for key in ["ids", "documents", "metadatas", "distances"]):
                    ids = query_results["ids"][0]
                    documents = query_results["documents"][0]
                    metadatas = query_results["metadatas"][0]
                    distances = query_results["distances"][0]

                    for i in range(len(ids)):
                        results.append({
                            "id": ids[i],
                            "content": documents[i],
                            "metadata": metadatas[i],
                            "relevance_score": 1.0 - (distances[i] / 2.0),  # Convert distance to score between 0-1
                            "collection": coll_name
                        })
            except Exception as e:
                logger.error(f"Error searching collection {coll_name}: {str(e)}")

        # Sort results by relevance score
        results.sort(key=lambda x: x["relevance_score"], reverse=True)

        # Limit total results
        return results[:n_results]

    def get_file_summary(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve summary for a specific file.

        Args:
            file_path: Path of the file to retrieve summary for

        Returns:
            Dictionary with file summary or None if not found
        """
        if self.client is None:
            if not self.connect():
                return None

        if "file_summaries" not in self.collections:
            logger.error("File summaries collection not found")
            return None

        try:
            # Create a safe ID from the file path
            safe_id = self._get_safe_id(file_path)

            # First try exact ID match
            result = self.collections["file_summaries"].get(ids=[safe_id])

            if result and result["documents"]:
                return {
                    "id": safe_id,
                    "summary": result["documents"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {}
                }

            # If not found, try searching by relative path
            where_clause = {"rel_path": os.path.basename(file_path)}
            result = self.collections["file_summaries"].get(where=where_clause)

            if result and result["documents"]:
                return {
                    "id": result["ids"][0],
                    "summary": result["documents"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {}
                }

            # If still not found, try searching by absolute path in metadata
            where_clause = {"file_path": file_path}
            result = self.collections["file_summaries"].get(where=where_clause)

            if result and result["documents"]:
                return {
                    "id": result["ids"][0],
                    "summary": result["documents"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {}
                }

            return None

        except Exception as e:
            logger.error(f"Error retrieving file summary for {file_path}: {str(e)}")
            return None

    def find_similar_code(
        self,
        code_snippet: str,
        n_results: int = 5,
        collection: str = "functions"
    ) -> List[Dict[str, Any]]:
        """
        Find similar code patterns across the codebase.

        Args:
            code_snippet: Code snippet to find similarities for
            n_results: Maximum number of results to return
            collection: Collection to search in (functions, classes, or file_summaries)

        Returns:
            List of similar code snippets with metadata
        """
        if self.client is None:
            if not self.connect():
                return []

        valid_collections = ["functions", "classes", "file_summaries"]
        if collection not in valid_collections:
            logger.error(f"Invalid collection {collection} for code search")
            return []

        if collection not in self.collections:
            logger.error(f"Collection {collection} not found")
            return []

        try:
            # Search the collection
            query_results = self.collections[collection].query(
                query_texts=[code_snippet],
                n_results=n_results
            )

            results = []

            # Process results
            if query_results and all(key in query_results for key in ["ids", "documents", "metadatas", "distances"]):
                ids = query_results["ids"][0]
                documents = query_results["documents"][0]
                metadatas = query_results["metadatas"][0]
                distances = query_results["distances"][0]

                for i in range(len(ids)):
                    results.append({
                        "id": ids[i],
                        "content": documents[i],
                        "metadata": metadatas[i],
                        "relevance_score": 1.0 - (distances[i] / 2.0),
                        "collection": collection
                    })

            return results

        except Exception as e:
            logger.error(f"Error finding similar code: {str(e)}")
            return []

    def filter_by_type(
        self,
        query: str,
        type_filter: str,
        n_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search with type filter (classes, functions, etc.)

        Args:
            query: Search query
            type_filter: Type of item to filter by (class, function, dependency)
            n_results: Maximum number of results to return

        Returns:
            List of search results matching the type filter
        """
        # Map type filter to collection
        type_map = {
            "class": "classes",
            "function": "functions",
            "dependency": "dependencies",
            "summary": "file_summaries"
        }

        if type_filter not in type_map:
            logger.error(f"Invalid type filter: {type_filter}")
            return []

        collection = type_map[type_filter]
        return self.search_codebase(query, n_results, collection)

    def get_file_contents(self, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all analysis data for a specific file.

        Args:
            file_path: Path of the file to retrieve data for

        Returns:
            Dictionary with different types of analysis data for the file
        """
        if self.client is None:
            if not self.connect():
                return {}

        result: Dict[str, List[Dict[str, Any]]] = {
            "summary": [],
            "classes": [],
            "functions": [],
            "dependencies": []
        }

        # Process file path to handle different forms
        basename = os.path.basename(file_path)

        try:
            # Get the file summary
            if "file_summaries" in self.collections:
                # Try exact ID first
                safe_id = self._get_safe_id(file_path)
                summary = self.collections["file_summaries"].get(ids=[safe_id])

                # If not found, try by filename
                if not summary["documents"]:
                    where_clause = {"filename": basename}
                    summary = self.collections["file_summaries"].get(where=where_clause)

                if summary and summary["documents"]:
                    for i, doc in enumerate(summary["documents"]):
                        result["summary"].append({
                            "id": summary["ids"][i],
                            "content": doc,
                            "metadata": summary["metadatas"][i] if summary["metadatas"] else {}
                        })

            # For each collection type, get data for this file
            for coll_type in ["classes", "functions", "dependencies"]:
                if coll_type in self.collections:
                    # Search by filename in metadata
                    where_clause = {"filename": basename}
                    items = self.collections[coll_type].get(where=where_clause)

                    if items and items["documents"]:
                        for i, doc in enumerate(items["documents"]):
                            result[coll_type].append({
                                "id": items["ids"][i],
                                "content": doc,
                                "metadata": items["metadatas"][i] if items["metadatas"] else {}
                            })

            return result

        except Exception as e:
            logger.error(f"Error retrieving file contents for {file_path}: {str(e)}")
            return result

    def list_analyzed_files(self) -> List[Dict[str, Any]]:
        """
        Get a list of all analyzed files in the database.

        Returns:
            List of file information dictionaries
        """
        if self.client is None:
            if not self.connect():
                return []

        try:
            if "file_summaries" not in self.collections:
                logger.error("File summaries collection not found")
                return []

            # Get all entries from file_summaries
            result = self.collections["file_summaries"].get()

            files = []
            if result and result["metadatas"]:
                for i, metadata in enumerate(result["metadatas"]):
                    files.append({
                        "id": result["ids"][i],
                        "file_path": metadata.get("file_path", "Unknown"),
                        "rel_path": metadata.get("rel_path", metadata.get("filename", "Unknown")),
                        "filename": metadata.get("filename", "Unknown"),
                        "total_lines": metadata.get("total_lines", 0),
                        "has_error": metadata.get("has_error", False)
                    })

            return files

        except Exception as e:
            logger.error(f"Error listing analyzed files: {str(e)}")
            return []

    def get_project_info(self) -> Dict[str, Any]:
        """
        Get information about the analyzed project.

        Returns:
            Dictionary with project metadata
        """
        if self.client is None:
            if not self.connect():
                return {}

        try:
            if "metadata" not in self.collections:
                logger.error("Metadata collection not found")
                return {}

            # Get project info
            info = self.collections["metadata"].get(ids=["project_info"])

            if info and info["metadatas"] and info["metadatas"][0]:
                return info["metadatas"][0]

            return {}

        except Exception as e:
            logger.error(f"Error retrieving project info: {str(e)}")
            return {}

    def _get_safe_id(self, file_path: str) -> str:
        """
        Create a safe ID from a file path.

        Args:
            file_path: File path to transform

        Returns:
            Safe ID string for ChromaDB
        """
        # Remove special characters and replace with underscores
        return file_path.replace('/', '_').replace('\\', '_').replace('.', '_').replace(' ', '_')