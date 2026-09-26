## Problem Description

When multiple database aliases are configured to use SQLite backends with persistent on-disk files (rather than in-memory databases), concurrent or sequential operations that require exclusive file access—such as creating, destroying, or cloning test databases—can fail with "database is locked" errors. This occurs because SQLite enforces file-level locking, and open connections from sibling database aliases within the same process can hold shared locks that block exclusive operations on the same or related database files. The core pattern is an **implicit assumption violation**: the system treats logically separate database aliases as fully independent resources, but at the file-system level they share a locking domain, breaking the expected symmetry between aliases.

## Root Cause Analysis

SQLite's locking model operates at the file level, not at the connection or alias level. When a framework opens connections to multiple database aliases early in a process (e.g., during test setup), each open connection may acquire at least a shared lock on its underlying file. When the framework later attempts an exclusive-lock operation on one of those files—such as unlinking, copying, or performing schema creation—any other open connection in the same process that touches the same file (or even a different alias that resolved to the same persistent file) will block the operation.

The cognitive trap is treating database aliases as isolated resources. In most database backends, connections to different aliases are indeed independent. But SQLite's file-level locking means that **any open connection in the same process can interfere with exclusive file operations**, even when the connections are logically separate. This is a symmetry-breaking problem: the abstraction of "independent aliases" does not hold under SQLite's concurrency model, and the framework's identity function—mapping alias → independent resource—is incomplete.

## Solution Strategy

### 识别信号
- 观测到的现象: `OperationalError: database is locked` during test database creation, destruction, or cloning when using multiple named SQLite databases with persistent (on-disk) test files.
- Deadlocks or hangs during test setup/teardown in multi-database SQLite configurations.
- The problem does **not** manifest with a single database alias or with purely in-memory (`:memory:`) SQLite databases.

### 解决步骤
1. **Locate the test database lifecycle methods** in the SQLite backend—specifically the methods responsible for creating, destroying, and cloning test databases.
2. **Identify the exclusive-lock operations**: pinpoint every code path that performs destructive or exclusive file-level operations (e.g., `os.unlink`, file copy, schema creation on a persistent SQLite file).
3. **Before each exclusive-lock operation, close sibling connections**: iterate over all database connections held by other aliases in the same process and explicitly close any that might hold locks on SQLite files. This must happen at the precise moment before the exclusive operation, not globally or eagerly.
4. **Guard the closure to the multi-persistent-database case**: only close sibling connections when the target is a persistent on-disk SQLite file. Skip this step for in-memory databases or single-alias configurations to avoid unnecessary disruption.
5. **Keep the change minimal and surgical**: do not alter connection pooling, method signatures, database routing, or the broader architecture. The fix should be a localized pre-operation cleanup.
6. **Add test coverage**: configure at least two persistent SQLite test databases under different aliases and verify that creation and teardown complete without locking errors.

### Why This Works

By closing sibling connections immediately before an exclusive file operation, we release any shared or reserved locks those connections hold on the SQLite file. This eliminates the file-level lock contention that causes the "database is locked" error. The fix is precise because it only intervenes at the moment of conflict—when exclusive access is needed—and does not disrupt normal operation for configurations where the problem does not arise (single database, in-memory databases, or non-SQLite backends). It correctly bridges the gap between the logical abstraction (independent aliases) and the physical reality (shared file-level locking domain).

## Boundary Cases

- **In-memory SQLite databases (`:memory:`)**: These do not use file-level locking and should not trigger sibling connection closure. The fix must detect and skip this case.
- **Single database alias**: No sibling connections exist, so the fix is a no-op. Ensure no regressions in this common configuration.
- **Multiple aliases resolving to the same physical file**: This is the most acute form of the problem. The fix must handle this case even when alias names differ.
- **Mixed backends** (e.g., one SQLite alias and one PostgreSQL alias): Closing the non-SQLite connection is unnecessary but harmless. The fix should ideally only close SQLite connections, but must at minimum not crash on non-SQLite backends.
- **Parallel test execution across processes**: File-level locking can also occur across processes. This fix addresses the single-process, multi-alias case; cross-process locking requires separate mitigation (e.g., unique test database file names per process).
- **Persistent test databases with `--keepdb`**: When test databases are preserved across runs, the creation path may be skipped but teardown or re-creation paths still need protection.

## PR Examples
- django__django-12113