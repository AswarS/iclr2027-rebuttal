## Problem Description

When a user-configurable list of directories (e.g., template or static file directories) is fed into a file-watching subsystem, an overly broad directory entry—such as the project root—can silently destabilize the autoreload mechanism. The directory-collection function trusts user configuration without validating scope, causing the file watcher to monitor the entire source tree as if it were a resource directory. This overwhelms or confuses the watcher's internal state (file modification times, directory snapshots), leading to silent failures: the autoreloader stops detecting code changes, enters restart loops, or fails to trigger reloads entirely. The configuration itself appears valid, so the breakage is invisible to the user.

## Root Cause Analysis

The underlying principle is a **boundary-validation gap** at the interface between user configuration and an internal subsystem with implicit scope assumptions. The directory-collection function resolves configured paths and hands them to the autoreload infrastructure without filtering for semantic appropriateness. The autoreloader was designed under the implicit assumption that watched directories would be narrowly scoped (e.g., a `templates/` folder), not encompassing the entire project tree. When a broad directory is introduced—either intentionally (the user points a template directory at the project root for convenience) or accidentally—the watcher's domain expands to cover all source files. This causes a **handler domain preemption**: the resource-watching subsystem claims ownership over files that belong to the code-change detection subsystem, and the two domains overlap destructively. The result is silent data loss in the form of missed reload signals, because the watcher's state is polluted beyond its design capacity.

This is fundamentally a **boundary-condition neglect** problem: the code assumes all configured directories are "well-behaved" and never validates that a directory's scope is compatible with the subsystem consuming it.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Autoreloader silently stops detecting source code changes after a configuration change
  - Autoreloader enters infinite restart loops or exhibits severe performance degradation
  - Adding a broad directory (e.g., project root) to a resource directory setting breaks code reloading, even though the setting appears valid
  - No error or warning is raised—the failure is entirely silent

### 解决步骤
1. **Trace the data flow**: Follow the configured directory list from the setting through the directory-collection/resolution function to where the returned set is consumed by the file watcher or autoreload infrastructure. Identify the exact function that gathers and yields directories without filtering.
2. **Identify the scope violation point**: Determine where the overly broad directory enters the watcher's state. This is typically the directory-collection function that resolves user-configured paths and returns them as a set to the autoreloader.
3. **Add a scope guard at the collection boundary**: Within the directory-gathering function, add a conditional check or filter that excludes directories which are parents of (or equal to) the project's source root. For example, skip any configured directory that would cause the watcher to encompass the entire source tree.
4. **Preserve valid configurations**: Ensure the filter is minimal and targeted—only exclude entries that demonstrably overlap with the code-change detection domain. All narrowly scoped, legitimate resource directories must continue to be watched normally.
5. **Add regression tests**: Write a test that configures the directory list to include the project root (or another broad parent directory) and verifies that (a) the autoreloader still correctly detects source file changes, (b) the broad directory is excluded from the watched set, and (c) no error is raised.

### Why This Works

The fix enforces a **scoping constraint** at the boundary where user configuration is translated into internal watcher state. By filtering at the directory-collection point—rather than restructuring the reload architecture—the solution addresses the root cause (unvalidated scope) with minimal, deterministic logic. The autoreload dispatch mechanism works correctly as long as each subsystem watches an appropriately scoped set of directories; the fix simply ensures that invariant holds. This transforms an implicit assumption ("configured directories will be narrow") into an explicit, enforced contract.

## Boundary Cases
- **Project root explicitly listed as a resource directory**: Must be detected and excluded, as it encompasses all source files and would preempt the code-change watcher's domain.
- **A directory that is a parent of the source root but not the root itself** (e.g., a shared parent in a monorepo): Should also be filtered if it contains the source tree, to prevent the same overlap.
- **Symlinked directories that resolve to the project root**: The filtering logic must operate on resolved (canonical) paths to catch symlink-based equivalences.
- **Multiple overlapping configured directories where none is the project root**: These may cause performance issues but do not preempt the code-change domain; the fix should not over-filter legitimate resource directories that happen to overlap each other.
- **Empty or nonexistent configured directories**: Should be handled gracefully (skipped) without interfering with the scope-validation logic.
- **Platform-specific path normalization** (e.g., case-insensitive filesystems on Windows): The parent-directory check must account for platform path semantics to avoid false negatives.

## PR Examples
- django__django-15388