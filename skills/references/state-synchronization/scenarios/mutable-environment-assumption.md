## Problem Description

A framework computes relative file paths for diagnostic output (error messages, stack traces, test reports) using the process's current working directory (CWD) as the implicit base. Between the framework's initialization and the moment it renders these paths, user-supplied code (plugins, fixtures, hooks, callbacks) can mutate the CWD — a piece of mutable global state. The resulting relative paths are silently wrong: they resolve to nonexistent or incorrect locations from the user's original shell/editor context, producing confusing or misleading output without any explicit error.

This is an instance of the broader **mutable-environment-assumption** pattern: code that reads a piece of process-global environmental state (CWD, locale, environment variables, signal handlers, etc.) at output time, implicitly assuming it still holds the value it had at initialization time, while an intervening execution phase allows arbitrary user code to mutate that state.

## Root Cause Analysis

The root cause is **treating a mutable environmental property as an invariant**. The current working directory is process-global, shared, mutable state. Any code running in the same process can change it at any time. When a framework computes `os.path.relpath(target, os.getcwd())` at display time, it couples the correctness of its output to the assumption that no intervening code has called `os.chdir()`.

The cognitive trap is subtle: developers often recognize *one* failure mode of CWD instability (the directory being deleted, causing an `OSError`) and add a guard for it, while completely missing the *other* failure mode (the directory being changed to a different valid directory). Both share the same root cause — **environmental state drift** — but the second produces silently wrong output rather than an exception, making it far harder to detect during development and testing.

The desynchronization between the framework's "intended base directory" (captured at startup) and the "actual CWD" (read at render time) is the state-synchronization failure at the heart of this pattern.

## Solution Strategy

### 识别信号
- 观测到的现象: **Incorrect error messages / wrong output** — file paths in diagnostic output point to wrong or nonexistent locations; paths that should be clickable in an IDE or navigable from the shell fail to resolve; users report that error locations "look wrong" but only when certain plugins or fixtures are active.
- Secondary signal: the problem is intermittent or configuration-dependent, appearing only when specific user code (that happens to call `os.chdir()`) runs before the output-rendering phase.

### 解决步骤
1. **Locate the stable reference point.** Find where the framework records its original invocation directory or root directory at startup (e.g., `config.invocation_dir`, `rootdir`, or equivalent). If no such value is stored, introduce one — capture `os.getcwd()` at the earliest reliable initialization point and store it immutably.
2. **Audit all relative-path computation sites.** Search for calls to `os.path.relpath()`, manual path subtraction, or any logic that implicitly depends on `os.getcwd()` for display/reporting purposes. Each site is a potential desynchronization point.
3. **Compare CWD against the stored reference at render time.** Before computing a relative path, check whether `os.getcwd()` still matches the stored invocation directory. If they differ, the relative path would be meaningless to the user.
4. **Fall back to absolute paths when state has drifted.** When the CWD has changed (or when the original directory has been deleted, raising `OSError`), emit the absolute path instead. This is universally correct regardless of CWD state.
5. **Wrap the computation in a robust guard.** Catch both `OSError` (directory deleted) and the logical divergence case (directory changed) in a single defensive block, falling back to absolute paths in either case.
6. **Add regression tests.** Write a test that explicitly calls `os.chdir()` to a different valid directory mid-execution, then verifies that all reported paths are correct and navigable from the original invocation directory.

### Why This Works

Relative paths are only meaningful with respect to a known, stable base directory. By detecting when the implicit base (CWD) has drifted from the explicit base (stored invocation directory) and falling back to absolute paths, the fix **decouples output correctness from mutable global state**. Absolute paths are universally navigable — they carry their own base, eliminating the dependency entirely. This approach is minimal and robust: it avoids complex plumbing to thread the original directory through every layer of the reporting stack, and it degrades gracefully (absolute paths are strictly more informative than wrong relative paths).

## Boundary Cases
- **CWD deleted entirely**: The `os.getcwd()` call itself raises `OSError`. The guard must catch this and fall back to absolute paths (computed from the stored reference, not from CWD).
- **CWD changed to a subdirectory of the original**: The relative path computation may *succeed* without error but produce a path like `../../actual/file.py` that is technically valid yet confusing. The CWD-equality check catches this.
- **CWD changed and then restored before rendering**: The paths will be correct, but tests should not rely on this — the guard should still be present since restoration is not guaranteed.
- **Concurrent/parallel execution**: In multi-process test runners, each worker may have its own CWD. The stored reference must be per-process or inherited correctly at fork time.
- **Symlinks and path normalization**: The CWD comparison should use `os.path.realpath()` or equivalent to avoid false negatives from symlinked directories that are logically the same.
- **Paths on different drives (Windows)**: `os.path.relpath()` raises `ValueError` when paths are on different drives. The fallback logic must handle this as another trigger for absolute-path output.

## PR Examples
- pytest-dev__pytest-7220