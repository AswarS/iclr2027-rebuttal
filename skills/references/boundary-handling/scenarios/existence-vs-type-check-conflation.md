## Problem Description

When a system resolves path-like identifiers (module names, directory paths, resource locators) to determine processing strategy, the routing logic may use a broad **existence check** (e.g., "does this path exist?") instead of a **type-specific check** (e.g., "is this a file?" or "is this a directory with the expected marker?"). This conflation causes incorrect routing when two structurally different entity types share the same base name — most commonly, a container (directory) and an item within it (file). The system silently selects the wrong processing branch, leading to crashes, wrong output, or subtle behavioral errors.

This pattern is especially prevalent in module/package resolution systems where a directory named `X` can coexist with a file `X.py` inside it (or alongside it), and the resolver must distinguish between regular packages, namespace packages, and standalone modules.

## Root Cause Analysis

The fundamental error is **equating "something exists at this path" with "this path is a valid entry point for a specific processing mode."** Each processing branch has distinct structural invariants:

- A **file-based entity** (e.g., a standalone module) requires the path to be a regular file.
- A **container-based entity** (e.g., a regular package) requires the path to be a directory **and** contain a specific marker file (e.g., `__init__.py`, `index.html`, a manifest).
- A **namespace entity** (e.g., a namespace package) is a directory that explicitly **lacks** the marker file.

A broad `path.exists()` check returns `True` for all three cases indiscriminately. When two entities share a base name at different levels of a hierarchy (e.g., directory `foo/` and file `foo/__init__.py`, or package `foo/` alongside module `foo.py`), the existence check silently resolves to whichever entity the filesystem finds first — typically the directory — and feeds it into a processing branch that expects a file, or vice versa. The developer's mental model assumes names are unique across entity types, but hierarchical naming systems routinely violate this assumption.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash/Exception**: Processing logic receives a directory where it expected a file (or vice versa), causing parse errors, read failures, or unexpected `None` returns.
  - **Wrong Output**: The system silently processes the wrong entity — e.g., analyzing a package directory as if it were a module file, producing missing or incorrect results.
  - **Inconsistent behavior**: The same logical name resolves correctly in some directory structures but fails when a container and item share a name.

### 解决步骤

1. **Locate the routing predicate**: Find the branching point where the system decides which processing path to take based on a path-like identifier. Look for calls like `os.path.exists()`, `Path.exists()`, or equivalent broad checks used as the sole discriminator.

2. **Audit what each branch actually requires**: For each downstream processing path, determine the precise structural property it depends on — is it a regular file? A directory with a specific marker file? A directory without one? Document these invariants explicitly.

3. **Replace the broad existence check with type-specific predicates**:
   - Use `os.path.isfile()` / `Path.is_file()` for branches that process file-based entities.
   - Use `os.path.isdir()` / `Path.is_dir()` **combined with** a marker-file check (e.g., `(path / '__init__.py').is_file()`) for container-based entities that require a marker.
   - Ensure entities matching neither specific check (e.g., namespace directories without a marker) fall through to a dedicated resolution strategy.

4. **Order the checks from most specific to least specific**: Check for regular packages (directory + marker) before namespace packages (directory without marker), and check for files before directories, to prevent ambiguous matches.

5. **Add regression tests**: Create test fixtures where a container and an item inside it share the same base name, and verify that each resolves to the correct processing branch.

### Why This Works

Each processing branch has **structural preconditions** that go beyond mere existence. By testing for the exact property each branch requires, the routing logic becomes a precise discriminator rather than a loose filter. This eliminates the ambiguity window where two different entity types could satisfy the same predicate. The principle is: **never use a supertype check (existence) where a subtype check (file-ness, directory-with-marker-ness) is what the downstream logic actually demands.**

## Boundary Cases

- **Container and item share the exact same base name** (e.g., directory `mymodule/` containing `mymodule/__init__.py` — the package name collides with the directory name at the filesystem level).
- **Namespace packages** (directories without `__init__.py`) that coexist alongside regular packages or modules with the same name — the absence of a marker file must route to a distinct strategy, not fall into the regular-package branch.
- **Symlinks**: A symlink may satisfy `exists()` but point to an entity of a different type than expected; type-specific checks on the resolved target are necessary.
- **Race conditions / stale caches**: A path that existed as a file at check time may have been replaced by a directory (or removed) by processing time — though this is an operational concern, type-specific checks reduce the blast radius.
- **Case-insensitive filesystems**: On systems where `Foo/` and `foo.py` may collide in resolution, the type check prevents silent misrouting even when name normalization is imperfect.

## PR Examples

- **pylint-dev__pylint-7114**: Module resolution logic used `os.path.exists()` to determine whether a given name was a package or module, causing incorrect classification when a directory and its contained `__init__.py` shared the same base name. The fix replaced the existence check with `os.path.isfile()` and `os.path.isdir()` checks combined with marker-file verification.