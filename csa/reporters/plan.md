# ChromaDB Reporter Feature Plan

## 1. New ChromaDBAnalysisReporter Class

```python
class ChromaDBAnalysisReporter(BaseAnalysisReporter):
    """
    Reporter that stores analysis results in a ChromaDB vector database.
    Each file analysis is stored with embeddings for semantic search.
    """
    
    def __init__(self, output_dir: str = "data/chroma"):
        self.output_dir = output_dir
        self.client = None
        self.collections = {}  # Different collections for different analysis types
        
    def initialize(self, files: List[str], source_dir: str) -> None:
        # Initialize ChromaDB client and collections
        # Create collections for: file_summaries, classes, functions, dependencies
        
    def update_file_analysis(self, file_analysis: Dict[str, Any], source_dir: str, remaining_files: List[str]) -> None:
        # For each file analysis:
        # 1. Store overall file summary in summaries collection
        # 2. Store each class definition in classes collection
        # 3. Store each function in functions collection
        # 4. Store dependencies in dependencies collection
        
    def finalize(self) -> None:
        # Persist all collections to disk
        # Create metadata file with analysis stats
```

## 2. ChromaDB Database Structure

- **Collections**:
  - `file_summaries`: Overall file summaries
  - `classes`: Class definitions with metadata
  - `functions`: Function definitions with metadata
  - `dependencies`: Import relationships
  
- **Document Structure**:
  - Each document has a unique ID (using file path as base)
  - Metadata includes: file_path, line_numbers, type, size
  - Text content contains the relevant analyzed segment

## 3. ChromaDBAnalysisRetriever Class

```python
class ChromaDBAnalysisRetriever:
    """
    Retriever for querying analysis data from ChromaDB.
    Supports semantic search across codebase analysis results.
    """
    
    def __init__(self, db_path: str = "data/chroma"):
        self.db_path = db_path
        self.client = None
        self.collections = {}
        
    def connect(self) -> None:
        # Connect to existing ChromaDB collections
        
    def search_codebase(self, query: str, n_results: int = 5, collection: str = "all") -> List[Dict]:
        # Search across specified or all collections
        
    def get_file_summary(self, file_path: str) -> Dict:
        # Retrieve summary for specific file
        
    def find_similar_code(self, code_snippet: str, n_results: int = 5) -> List[Dict]:
        # Find similar code patterns across the codebase
        
    def filter_by_type(self, query: str, type_filter: str, n_results: int = 5) -> List[Dict]:
        # Search with type filter (classes, functions, etc.)
```

## 4. Implementation Steps

1. Add ChromaDB to project dependencies
2. Create the ChromaDBAnalysisReporter class
3. Create the ChromaDBAnalysisRetriever class
4. Update analyzer.py to support the new reporter
5. Add CLI options to use ChromaDB reporter
6. Create sample queries for the README

## 5. Dependencies

```
chromadb>=0.4.18
sentence-transformers>=2.2.2
```

## 6. Usage Examples

```python
# Analyze codebase using ChromaDB reporter
analyze_codebase(
    source_dir="./src",
    reporter_type="chromadb",
    output_dir="./data/chroma"
)

# Query analysis results
retriever = ChromaDBAnalysisRetriever("./data/chroma")
results = retriever.search_codebase("file handling implementation")
```

-------------------------------------------
DO NOT EDIT ABOVE THESE LINES!!!
-------------------------------------------

## 7. Detailed Implementation Plan

### Step 1: Set up ChromaDB dependencies
- Add ChromaDB and sentence-transformers to requirements.txt
- Create a data directory structure for storing the database

### Step 2: Create ChromaDBAnalysisReporter class
1. Create file `csa/reporters/chromadb.py`
2. Implement basic class structure inheriting from BaseAnalysisReporter
3. Implement database connection and initialization logic
4. Add document creation logic for different analysis components
5. Implement metadata extraction for better search capabilities

### Step 3: Create ChromaDBAnalysisRetriever class
1. Create file `csa/retrieval/chromadb_retriever.py` 
2. Implement connection to existing ChromaDB
3. Add query methods for different use cases
4. Implement results formatting for user-friendly display
5. Add filter options for more targeted searches

### Step 4: Update analyzer.py
1. Add support for ChromaDB reporter selection
2. Update reporter factory to include ChromaDB option
3. Add output directory parameter handling

### Step 5: Update CLI
1. Add ChromaDB reporter option to CLI arguments
2. Add database path configuration option
3. Add collection configuration options

### Step 6: Testing
1. Create unit tests for ChromaDBAnalysisReporter
2. Create unit tests for ChromaDBAnalysisRetriever
3. Create integration tests for end-to-end workflow

### Step 7: Documentation
1. Update README with ChromaDB reporter information
2. Add examples of query usage
3. Document database structure and customization options

## 8. Progress Tracking

1. ✅ Created initial feature plan
2. ✅ Created directory structure (`csa/retrieval/`)
3. ✅ Implemented `ChromaDBAnalysisReporter` class in `csa/reporters/chromadb.py`
4. ✅ Implemented `ChromaDBAnalysisRetriever` class in `csa/retrieval/chromadb_retriever.py`
5. ✅ Updated `csa/reporters/__init__.py` to include the new reporter
6. ✅ Created `csa/retrieval/__init__.py` for the retrieval package
7. ✅ Updated `analyzer.py` to support the ChromaDB reporter
8. ✅ Updated `cli.py` to add CLI options for the ChromaDB reporter
9. ✅ Added ChromaDB dependencies to `requirements.txt`
10. ✅ Created example script `examples/query_chromadb.py` for querying the ChromaDB database

ERRORS:
ruff.....................................................................Failed
- hook id: ruff
- files were modified by this hook

Found 1 error (1 fixed, 0 remaining).

ruff-format..............................................................Passed
mypy.....................................................................Failed
- hook id: mypy
- exit code: 1

csa/retrieval/chromadb_retriever.py:69: error: Statement is unreachable  [unreachable]
csa/retrieval/chromadb_retriever.py:161: error: "str" has no attribute "query"  [attr-defined]
csa/reporters/chromadb.py:73: error: Statement is unreachable  [unreachable]
csa/reporters/chromadb.py:87: error: Statement is unreachable  [unreachable]
csa/reporters/chromadb.py:151: error: Right operand of "or" is never evaluated  [unreachable]
csa/reporters/chromadb.py:155: error: Statement is unreachable  [unreachable]
csa/reporters/chromadb.py:220: error: Statement is unreachable  [unreachable]
csa/analyzer.py:602: error: Name "reporter" already defined on line 598  [no-redef]
Found 8 errors in 3 files (checked 22 source files)