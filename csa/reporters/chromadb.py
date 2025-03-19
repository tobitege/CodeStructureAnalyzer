import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from csa.reporters.reporters import BaseAnalysisReporter

logger = logging.getLogger(__name__)


class ChromaDBAnalysisReporter(BaseAnalysisReporter):
    """
    Reporter that stores analysis results in a ChromaDB vector database.

    This class provides methods to search and retrieve code analysis data stored in a ChromaDB vector database,
    with separate collections for different aspects of the code (summaries, classes,
    functions, dependencies). Each entry is stored with appropriate metadata and
    embeddings for semantic search.
    """

    def __init__(self, output_dir: str = "data/chroma"):
        """
        Initialize the ChromaDB reporter.

        Args:
            output_dir: Directory path where the ChromaDB data will be stored
        """
        # Normalize path to handle Windows backslashes properly
        self.output_dir = os.path.normpath(output_dir)
        self.client: Optional[chromadb.PersistentClient] = None
        self.collections: dict[str, chromadb.api.models.Collection] = {}
        self.embedding_function = None
        self.source_dir = ""
        logger.info(f"ChromaDB reporter initialized with output_dir: {self.output_dir}")

    def initialize(self, files: List[str], source_dir: str) -> None:
        """
        Initialize the ChromaDB client and collections.

        Args:
            files: List of file paths to be analyzed
            source_dir: Source directory path
        """
        self.source_dir = source_dir
        logger.info(f"Initializing ChromaDB with source_dir: {source_dir}")

        # Create output directory if it doesn't exist
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info(f"Created output directory: {self.output_dir}")
        except Exception as e:
            logger.error(f"Error creating output directory {self.output_dir}: {str(e)}")
            raise

        # Initialize ChromaDB client with persistent storage
        try:
            logger.info(f"Creating ChromaDB PersistentClient at path: {self.output_dir}")
            self.client = chromadb.PersistentClient(
                path=self.output_dir,
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info(f"ChromaDB PersistentClient created successfully")

            # Use sentence-transformers for embeddings
            logger.info("Loading embedding function")
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            logger.info("Embedding function loaded successfully")

            # Define collections to create
            collections_config = [
                ("file_summaries", "Overall file summaries and metadata"),
                ("classes", "Class definitions and their documentation"),
                ("functions", "Function and method definitions"),
                ("dependencies", "Import relationships between files")
            ]

            logger.info(f"Creating {len(collections_config)} collections")

            # Track success in creating collections
            collection_success = True

            for name, description in collections_config:
                try:
                    logger.info(f"Creating collection: {name}")
                    collection = self.client.get_or_create_collection(
                        name=name,
                        embedding_function=self.embedding_function,
                        metadata={"description": description}
                    )
                    self.collections[name] = collection
                    logger.info(f"Successfully created collection: {name}")
                except Exception as e:
                    collection_success = False
                    logger.error(f"Error creating collection {name}: {str(e)}")

            if not collection_success:
                logger.error("Failed to create all collections")

            # Verify collections were created
            if "file_summaries" not in self.collections:
                logger.error("Critical: file_summaries collection not created")

            # List all collections to verify they were created
            all_collections = self.client.list_collections()
            logger.info(f"Available collections: {all_collections}")  # In v0.6.0+, these are already strings

            # Store basic project metadata
            try:
                logger.info("Creating metadata collection")
                metadata_collection = self.client.get_or_create_collection(
                    name="metadata",
                    embedding_function=self.embedding_function
                )

                # Add project metadata
                logger.info("Adding project metadata")
                metadata_collection.upsert(
                    ids=["project_info"],
                    documents=[f"Project analysis for {source_dir}"],
                    metadatas=[{
                        "source_dir": source_dir,
                        "file_count": len(files),
                        "analysis_date": str(__import__('datetime').datetime.now())
                    }]
                )

                # Store list of files for reference
                file_chunks: List[List[str]] = []
                file_ids = []
                file_metadatas = []

                # Split files into chunks of 50 to avoid token limits
                for i, file_path in enumerate(files):
                    chunk_id = i // 50
                    if len(file_chunks) <= chunk_id:
                        file_chunks.append([])
                    file_chunks[chunk_id].append(file_path)

                # Store each chunk
                documents = []
                for i, chunk in enumerate(file_chunks):
                    file_ids.append(f"files_chunk_{i}")
                    documents.append("\n".join(chunk))
                    file_metadatas.append({
                        "type": "file_list",
                        "chunk": i,
                        "count": len(chunk)
                    })

                metadata_collection.upsert(
                    ids=file_ids,
                    documents=documents,
                    metadatas=file_metadatas
                )

                self.collections["metadata"] = metadata_collection
                logger.info("Metadata collection created and populated successfully")
            except Exception as e:
                logger.error(f"Error storing project metadata: {str(e)}")

        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {str(e)}")
            raise

    def update_file_analysis(
        self, file_analysis: Dict[str, Any], source_dir: str, remaining_files: List[str]
    ) -> None:
        """
        Update the ChromaDB database with analysis results for a file.

        Args:
            file_analysis: Analysis results for a file
            source_dir: Source directory path
            remaining_files: List of files remaining to analyze
        """
        if self.client is None:
            logger.error("ChromaDB client not initialized, cannot update file analysis")
            return

        file_path = file_analysis.get('file_path', '')
        if not file_path:
            logger.error("File path missing in analysis results")
            return

        # Verify collections exist before proceeding
        if not self.collections:
            logger.error("No collections available for storing analysis results")
            try:
                logger.info("Attempting to reconnect to existing collections...")
                for collection_name in ["file_summaries", "classes", "functions", "dependencies", "metadata"]:
                    try:
                        self.collections[collection_name] = self.client.get_collection(
                            name=collection_name,
                            embedding_function=self.embedding_function
                        )
                        logger.info(f"Successfully reconnected to collection: {collection_name}")
                    except Exception as e:
                        logger.error(f"Failed to reconnect to collection {collection_name}: {str(e)}")
            except Exception as e:
                logger.error(f"Failed to reconnect to collections: {str(e)}")
                return

        # Handle error case
        if 'error' in file_analysis:
            logger.warning(f"Error in file analysis for {file_path}: {file_analysis['error']}")
            # Store error information
            try:
                if "file_summaries" in self.collections:
                    self.collections["file_summaries"].upsert(
                        ids=[self._get_safe_id(file_path)],
                        documents=[f"Error analyzing file: {file_analysis['error']}"],
                        metadatas=[{
                            "file_path": file_path,
                            "has_error": True,
                            "error_message": file_analysis.get('error', ''),
                        }]
                    )
            except Exception as e:
                logger.error(f"Error storing file error information: {str(e)}")
            return

        # Process file summary
        self._store_file_summary(file_analysis, file_path)

        # Process classes, functions, and dependencies
        analyses = file_analysis.get('analyses', [])
        if analyses:
            classes = set()
            functions = set()
            dependencies = set()

            # Gather all unique items from analyses
            for analysis in analyses:
                if 'classes' in analysis:
                    for cls in analysis['classes']:
                        classes.add(cls)

                if 'functions' in analysis:
                    for func in analysis['functions']:
                        functions.add(func)

                if 'dependencies' in analysis:
                    for dep in analysis['dependencies']:
                        dependencies.add(dep)

            # Store classes
            self._store_classes(file_path, classes)

            # Store functions
            self._store_functions(file_path, functions)

            # Store dependencies
            self._store_dependencies(file_path, dependencies)

    def finalize(self) -> None:
        """
        Finalize the ChromaDB database.
        """
        if self.client is None:
            logger.warning("ChromaDB client not initialized, nothing to finalize")
            return

        # Update metadata with completion status
        try:
            if "metadata" in self.collections:
                self.collections["metadata"].update(
                    ids=["project_info"],
                    metadatas=[{
                        "completed": True,
                        "completion_date": str(__import__('datetime').datetime.now())
                    }]
                )

                logger.info(f"ChromaDB analysis data stored in {self.output_dir}")

                # Generate statistics for collections
                stats = {}
                for name, collection in self.collections.items():
                    count = collection.count()
                    stats[name] = count

                logger.info(f"ChromaDB collection statistics: {stats}")
        except Exception as e:
            logger.error(f"Error finalizing ChromaDB: {str(e)}")

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

    def _store_file_summary(self, file_analysis: Dict[str, Any], file_path: str) -> None:
        """
        Store file summary in the database.

        Args:
            file_analysis: Analysis results for a file
            file_path: Path to the file
        """
        try:
            summary = file_analysis.get('summary', 'No summary available.')

            # Get file metadata
            rel_path = self._get_relative_path(file_path)
            total_lines = file_analysis.get('total_lines', 0)

            # Check if collection exists before attempting to use it
            if "file_summaries" not in self.collections:
                logger.error(f"Cannot store file summary: file_summaries collection not available")
                return

            # Store in summary collection
            self.collections["file_summaries"].upsert(
                ids=[self._get_safe_id(file_path)],
                documents=[summary],
                metadatas=[{
                    "file_path": file_path,
                    "rel_path": rel_path,
                    "filename": os.path.basename(file_path),
                    "extension": os.path.splitext(file_path)[1],
                    "total_lines": total_lines,
                    "has_error": file_analysis.get('has_errors', False),
                    "oversized_file": file_analysis.get('oversized_file', False),
                }]
            )
            logger.info(f"Successfully stored summary for {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error storing file summary for {file_path}: {str(e)}")

    def _store_classes(self, file_path: str, classes: Set[str]) -> None:
        """
        Store class information in the database.

        Args:
            file_path: Path to the file
            classes: Set of class names and information
        """
        if not classes:
            return

        # Check if collection exists before attempting to use it
        if "classes" not in self.collections:
            logger.error(f"Cannot store classes: classes collection not available")
            return

        try:
            ids = []
            documents = []
            metadatas = []

            rel_path = self._get_relative_path(file_path)

            for i, class_info in enumerate(classes):
                # Create a unique ID for each class
                class_id = f"{self._get_safe_id(file_path)}_class_{i}"
                ids.append(class_id)
                documents.append(class_info)

                # Extract class name from class_info if possible
                class_name = class_info
                if ":" in class_info:
                    class_name = class_info.split(":", 1)[0].strip()

                metadatas.append({
                    "file_path": file_path,
                    "rel_path": rel_path,
                    "filename": os.path.basename(file_path),
                    "class_name": class_name,
                    "type": "class"
                })

            self.collections["classes"].upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            logger.info(f"Successfully stored {len(classes)} classes for {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error storing classes for {file_path}: {str(e)}")

    def _store_functions(self, file_path: str, functions: Set[str]) -> None:
        """
        Store function information in the database.

        Args:
            file_path: Path to the file
            functions: Set of function names and information
        """
        if not functions:
            return

        # Check if collection exists before attempting to use it
        if "functions" not in self.collections:
            logger.error(f"Cannot store functions: functions collection not available")
            return

        try:
            ids = []
            documents = []
            metadatas = []

            rel_path = self._get_relative_path(file_path)

            for i, function_info in enumerate(functions):
                # Create a unique ID for each function
                function_id = f"{self._get_safe_id(file_path)}_function_{i}"
                ids.append(function_id)
                documents.append(function_info)

                # Extract function name from function_info if possible
                function_name = function_info
                if "(" in function_info:
                    function_name = function_info.split("(", 1)[0].strip()

                metadatas.append({
                    "file_path": file_path,
                    "rel_path": rel_path,
                    "filename": os.path.basename(file_path),
                    "function_name": function_name,
                    "type": "function"
                })

            self.collections["functions"].upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            logger.info(f"Successfully stored {len(functions)} functions for {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error storing functions for {file_path}: {str(e)}")

    def _store_dependencies(self, file_path: str, dependencies: Set[str]) -> None:
        """
        Store dependency information in the database.

        Args:
            file_path: Path to the file
            dependencies: Set of dependency information
        """
        if not dependencies:
            return

        # Check if collection exists before attempting to use it
        if "dependencies" not in self.collections:
            logger.error(f"Cannot store dependencies: dependencies collection not available")
            return

        try:
            ids = []
            documents = []
            metadatas = []

            rel_path = self._get_relative_path(file_path)

            for i, dependency_info in enumerate(dependencies):
                # Create a unique ID for each dependency
                dependency_id = f"{self._get_safe_id(file_path)}_dependency_{i}"
                ids.append(dependency_id)
                documents.append(dependency_info)

                # Extract module name from dependency_info if possible
                module_name = dependency_info
                if " " in dependency_info:
                    parts = dependency_info.split(" ", 2)
                    if len(parts) >= 2:
                        module_name = parts[1]

                metadatas.append({
                    "file_path": file_path,
                    "rel_path": rel_path,
                    "filename": os.path.basename(file_path),
                    "module_name": module_name,
                    "type": "dependency"
                })

            self.collections["dependencies"].upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            logger.info(f"Successfully stored {len(dependencies)} dependencies for {os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"Error storing dependencies for {file_path}: {str(e)}")

    def _get_relative_path(self, file_path: str) -> str:
        """
        Get path relative to source directory.

        Args:
            file_path: Absolute file path

        Returns:
            Relative path
        """
        try:
            file_path_obj = Path(file_path)
            source_path = Path(self.source_dir)

            # For absolute paths, try to make them relative to source_dir
            if file_path_obj.is_absolute() and source_path.is_absolute():
                try:
                    rel_path = str(file_path_obj.relative_to(source_path))
                except ValueError:
                    # If not a subpath, just use the filename
                    rel_path = file_path_obj.name
            else:
                # For relative paths, use as is
                rel_path = file_path

            return rel_path

        except Exception:
            # Fallback to basename if there's an error
            return os.path.basename(file_path)