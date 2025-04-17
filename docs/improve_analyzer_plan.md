# Improvement Plan for `analyze_codebase`

Below is an implementation‑ready, incremental roadmap.  
Each item is self‑contained—tackle them one‑by‑one.

---

## 1. Extract Long‑Running Logic into Helpers

|            | Details |
|------------|---------|
| **Why**    | `analyze_codebase` mixes discovery, reporting, per‑file analysis, and cancellation logic, which complicates testing and maintenance. |
| **What**   | - `collect_files()` → wraps discovery / resume logic.<br>- `process_file()` → wraps try/except body that calls `analyze_file` and updates the reporter.<br>- `should_cancel()` → tiny helper. |
| **Benefit**| Clearer flow, easier unit testing, paves the way for concurrency. |

---

## 2. Global Progress Bar Across Files

|            | Details |
|------------|---------|
| **Why**    | Users only see per‑file progress; no view of overall progress. |
| **What**   | Instantiate `tqdm(total=len(files), desc="Files", unit="file")` outside the loop and update it inside `process_file`. |
| **Benefit**| Immediate UX improvement without functional changes. |

---

## 3. Robust Resume via Checkpoint File

|            | Details |
|------------|---------|
| **Why**    | Current resume relies on reporter‑specific logic; fragile. |
| **What**   | Write each analyzed path to `.csa_analyzed` (JSON‑lines). Read it on startup and subtract from discovery list. Support a `--fresh` flag to ignore the checkpoint. |
| **Benefit**| Resilient restarts even when output files are missing or corrupted. |

---

## 4. Opt‑In Parallelism

|            | Details |
|------------|---------|
| **Why**    | IO‑bound workload can benefit from concurrency. |
| **What**   | Add `max_workers` param. If > 1 use `ThreadPoolExecutor` (or `ProcessPoolExecutor` after confirming picklability) around `process_file`. Respect `cancel_callback` via a shared `threading.Event`. |
| **Benefit**| Significant speed‑ups on large repositories. |

---

## 5. Centralized Retry & Timeout Policy

|            | Details |
|------------|---------|
| **Why**    | Retry logic is duplicated in `analyze_file`. |
| **What**   | Move it into `CodeAnalyzer.safe_analyze_chunk()`, handling timeouts/back‑off. Remove inner `while retry` loop from `analyze_file`. |
| **Benefit**| Single place to tweak policy; cleaner chunk loop. |

---

## 6. Pluggable Reporter Registry

|            | Details |
|------------|---------|
| **Why**    | `if/else` on reporter type is brittle. |
| **What**   | Maintain `REPORTERS: dict[str, type[BaseAnalysisReporter]]`, allow third‑party registration via entry‑points or config. Replace `if/else` with a lookup, raise informative error on unknown type. |
| **Benefit**| Clean separation, easy to add reporters like HTML/JSON/SQLite. |

---

## 7. Per‑File Time Budget

|            | Details |
|------------|---------|
| **Why**    | Single large file can monopolize the run. |
| **What**   | Add `file_time_budget` (seconds). Track elapsed time; after each chunk stop further processing when budget exceeded and mark as partial. |
| **Benefit**| Predictable runtime, graceful degradation. |

---

## 8. Configurable Logging Verbosity

|            | Details |
|------------|---------|
| **Why**    | Current mix of `print`, `logger`, and `tqdm.write` is noisy. |
| **What**   | Add `verbose` flag (0 = WARN, 1 = INFO, 2 = DEBUG). Configure `logging.basicConfig` early; redirect `tqdm.write` to logger with custom handler. |
| **Benefit**| Cleaner console, better CI/CD integration. |

---

## 9. Command‑Line Interface

|            | Details |
|------------|---------|
| **Why**    | Users shouldn’t need to write Python snippets. |
| **What**   | New `cli.py` (entry point `csa-analyze`) mapping CLI args to `analyze_codebase`. Return exit codes: 0 success, 1 partial errors, 2 aborted. |
| **Benefit**| Improves usability and automation. |

---

## 10. Unit & Integration Tests

|            | Details |
|------------|---------|
| **Why**    | Guard against regressions from the refactors above. |
| **What**   | Use temp dirs with dummy files, stubbed `LLMProvider`. Test discovery, resume, cancellation, oversize logic, reporter outputs. |
| **Benefit**| Confidence in future changes and easier code reviews. |

---

### Recommended Order of Implementation

1. **Helpers & Progress Bar** (Items 1‑2)  
2. **Resume & Reporter Registry** (Items 3‑6, low risk)  
3. **Retry, Budget, Parallelism** (Items 5, 7, 4)  
4. **Logging, CLI, Tests** (Items 8‑10)

Implementing this roadmap will make the analysis pipeline cleaner, faster, extensible, and easier to maintain—without changing existing functionality.
