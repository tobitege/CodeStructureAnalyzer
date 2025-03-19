#!/usr/bin/env python3
"""
Example script to demonstrate querying a ChromaDB analysis database.

Usage:
usage: query_chromadb.py [-h] [--db-path DB_PATH] {search,list-files,file-details,similar-code} ...

Example:
python examples/query_chromadb.py --db-path "csa/data/chroma" list-files
python examples/query_chromadb.py --db-path "csa/data/chroma" file-details "csa/analyzer.py"
python examples/query_chromadb.py --db-path "csa/data/chroma" similar-code "code snippet" --collection functions
python examples/query_chromadb.py --db-path "csa/data/chroma" search "chromadb" --collection functions
"""

import argparse
import logging
import os
import sys
from typing import List, Dict, Any, Optional

# Add parent directory to path to allow imports from csa
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csa.retrieval import ChromaDBAnalysisRetriever

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def display_results(results: List[Dict[str, Any]], show_content: bool = True) -> None:
    """
    Display search results in a human-readable format.

    Args:
        results: List of search results
        show_content: Whether to show the full content or just metadata
    """
    if not results:
        print("No results found.")
        return

    print(f"\nFound {len(results)} results:")
    print("-" * 80)

    for i, result in enumerate(results):
        # Extract metadata
        metadata = result.get("metadata", {})
        collection = result.get("collection", "Unknown")
        score = result.get("relevance_score", 0.0)

        # Basic information always shown
        print(f"Result {i+1}/{len(results)} [{collection}] (Score: {score:.2f})")

        # File information if available
        if "file_path" in metadata:
            rel_path = metadata.get("rel_path", metadata.get("filename", "Unknown"))
            print(f"File: {rel_path}")

        # Type-specific information
        if collection == "classes":
            print(f"Class: {metadata.get('class_name', 'Unknown')}")
        elif collection == "functions":
            print(f"Function: {metadata.get('function_name', 'Unknown')}")
        elif collection == "dependencies":
            print(f"Module: {metadata.get('module_name', 'Unknown')}")

        # Show content if requested
        if show_content:
            content = result.get("content", "No content available")
            print("\nContent:")
            print(content)

        print("-" * 80)


def search_codebase(
    db_path: str,
    query: str,
    collection: str = "all",
    n_results: int = 5,
    filters: Optional[Dict[str, Any]] = None
) -> None:
    """
    Search the codebase analysis in ChromaDB.

    Args:
        db_path: Path to the ChromaDB database
        query: Search query
        collection: Collection to search in, or "all" for all collections
        n_results: Maximum number of results to return
        filters: Metadata filters to apply
    """
    # Initialize the retriever
    retriever = ChromaDBAnalysisRetriever(db_path)

    # Connect to the database
    if not retriever.connect():
        logger.error(f"Failed to connect to ChromaDB at {db_path}")
        return

    # Get project info
    project_info = retriever.get_project_info()
    if project_info:
        source_dir = project_info.get("source_dir", "Unknown")
        file_count = project_info.get("file_count", 0)
        analysis_date = project_info.get("analysis_date", "Unknown")
        print(f"Connected to analysis database for {source_dir}")
        print(f"Contains {file_count} files, analyzed on {analysis_date}")

    # Execute the search
    print(f"\nSearching for: {query}")
    if collection != "all":
        print(f"In collection: {collection}")
    if filters:
        print(f"With filters: {filters}")

    results = retriever.search_codebase(
        query=query,
        n_results=n_results,
        collection=collection,
        filters=filters
    )

    # Display results
    display_results(results)


def list_files(db_path: str) -> None:
    """
    List all files in the analysis database.

    Args:
        db_path: Path to the ChromaDB database
    """
    # Initialize the retriever
    retriever = ChromaDBAnalysisRetriever(db_path)

    # Connect to the database
    if not retriever.connect():
        logger.error(f"Failed to connect to ChromaDB at {db_path}")
        return

    # Get all files
    files = retriever.list_analyzed_files()

    if not files:
        print("No files found in the database.")
        return

    print(f"\nFound {len(files)} files in the database:")
    print("-" * 80)

    for i, file_info in enumerate(files):
        filename = file_info.get("filename", "Unknown")
        rel_path = file_info.get("rel_path", filename)
        total_lines = file_info.get("total_lines", 0)
        has_error = file_info.get("has_error", False)

        status = "❌ Error" if has_error else "✓ OK"
        print(f"{i+1}. {rel_path} ({total_lines} lines) - {status}")

    print("-" * 80)


def get_file_details(db_path: str, file_path: str) -> None:
    """
    Get detailed information about a specific file.

    Args:
        db_path: Path to the ChromaDB database
        file_path: Path of the file to retrieve details for
    """
    # Initialize the retriever
    retriever = ChromaDBAnalysisRetriever(db_path)

    # Connect to the database
    if not retriever.connect():
        logger.error(f"Failed to connect to ChromaDB at {db_path}")
        return

    # Get all analysis data for the file
    file_data = retriever.get_file_contents(file_path)

    if not any(file_data.values()):
        print(f"No information found for file: {file_path}")
        return

    print(f"\nFile details for: {file_path}")
    print("-" * 80)

    # Print summary
    if file_data["summary"]:
        summary = file_data["summary"][0]
        print("\n## Summary")
        print(summary.get("content", "No summary available"))

    # Print classes
    if file_data["classes"]:
        print("\n## Classes")
        for cls in file_data["classes"]:
            print(f"- {cls.get('content', 'No class information')}")

    # Print functions
    if file_data["functions"]:
        print("\n## Functions")
        for func in file_data["functions"]:
            print(f"- {func.get('content', 'No function information')}")

    # Print dependencies
    if file_data["dependencies"]:
        print("\n## Dependencies")
        for dep in file_data["dependencies"]:
            print(f"- {dep.get('content', 'No dependency information')}")

    print("-" * 80)


def find_similar_code(db_path: str, code_snippet: str, collection: str = "functions") -> None:
    """
    Find code similar to the provided snippet.

    Args:
        db_path: Path to the ChromaDB database
        code_snippet: Code snippet to find similarities for
        collection: Collection to search in
    """
    # Initialize the retriever
    retriever = ChromaDBAnalysisRetriever(db_path)

    # Connect to the database
    if not retriever.connect():
        logger.error(f"Failed to connect to ChromaDB at {db_path}")
        return

    print(f"\nFinding code similar to:")
    print("-" * 40)
    print(code_snippet)
    print("-" * 40)

    # Execute the search
    results = retriever.find_similar_code(
        code_snippet=code_snippet,
        collection=collection
    )

    # Display results
    display_results(results)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Query a ChromaDB code analysis database"
    )

    parser.add_argument(
        "--db-path",
        default="data/chroma",
        help="Path to the ChromaDB database directory"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search the codebase")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--collection",
        default="all",
        choices=["all", "file_summaries", "classes", "functions", "dependencies"],
        help="Collection to search in"
    )
    search_parser.add_argument(
        "--n-results",
        type=int,
        default=5,
        help="Maximum number of results to return"
    )
    search_parser.add_argument(
        "--filter",
        action="append",
        help="Metadata filters in the format key=value"
    )

    # List files command
    subparsers.add_parser("list-files", help="List all analyzed files")

    # File details command
    file_parser = subparsers.add_parser("file-details", help="Get details for a specific file")
    file_parser.add_argument("file_path", help="Path of the file to get details for")

    # Similar code command
    similar_parser = subparsers.add_parser("similar-code", help="Find similar code")
    similar_parser.add_argument("code_snippet", help="Code snippet to find similarities for")
    similar_parser.add_argument(
        "--collection",
        default="functions",
        choices=["functions", "classes", "file_summaries"],
        help="Collection to search in"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    if not args.command:
        print("No command specified. Use --help for available commands.")
        return 1

    # Parse filters if provided
    filters = {}
    if hasattr(args, "filter") and args.filter:
        for filter_str in args.filter:
            if "=" in filter_str:
                key, value = filter_str.split("=", 1)
                filters[key.strip()] = value.strip()

    # Execute the requested command
    if args.command == "search":
        search_codebase(
            args.db_path,
            args.query,
            args.collection,
            args.n_results,
            filters
        )
    elif args.command == "list-files":
        list_files(args.db_path)
    elif args.command == "file-details":
        get_file_details(args.db_path, args.file_path)
    elif args.command == "similar-code":
        find_similar_code(args.db_path, args.code_snippet, args.collection)

    return 0


if __name__ == "__main__":
    sys.exit(main())