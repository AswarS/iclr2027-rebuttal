## Problem Description

When a system accepts user-defined regex or glob patterns intended to match against file paths, and those file paths are constructed internally during operations like recursive directory traversal, a mismatch can occur between the canonical form users expect and the non-canonical form the system actually produces. This causes pattern-matching filters (ignore lists, exclude rules, etc.) to silently fail — the patterns never match, and the user receives no indication that their configuration is ineffective.

This pattern is especially insidious because it manifests as **silent data loss** or **wrong output**: the system appears to function normally but simply skips the filtering step the user intended. It is environment-dependent, often only surfacing on specific operating systems, with recursive (vs. non-recursive) traversal, or when paths contain redundant components like `./`, `..`, or mixed separators.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation**: developers assume that internally-constructed file paths will naturally be in the same canonical form that users write in their configuration. This assumption breaks down for several reasons:

1. **Platform-dependent separators**: Windows uses `\` while Unix uses `/`. Path-joining utilities may produce separators that differ from what users write in regex patterns.
2. **Redundant path components**: Recursive directory walking often produces paths like `src/./gen/file.py` or `src//gen/file.py` due to how parent directories are concatenated with child entries.
3. **Inconsistent normalization across code paths**: A system may normalize paths in one traversal mode (e.g., non-recursive) but not another (e.g., recursive), creating intermittent failures that are hard to reproduce.
4. **Regex is literal**: Unlike glob matching, which may tolerate some path variation, regex patterns treat `.`, `/`, and `\` as literal or special characters. A single extra `./` in the path will cause a well-formed regex to fail silently.

The cognitive trap is that developers test on a single platform with simple, already-canonical paths and never encounter the divergence. The failure only appears in real-world usage with nested directories, cross-platform CI, or non-trivial project structures.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - User-configured ignore/exclude path patterns have **no effect**, especially during recursive operations
  - Filtering works for top-level files but fails for files discovered in subdirectories
  - Patterns work on one OS but not another (e.g., Linux vs. Windows)
  - Debug logging reveals paths with unexpected formats (`./`, mixed separators, double slashes) being compared against user patterns
  - No errors or warnings are emitted — the mismatch is completely silent

### 解决步骤
1. **Audit all pattern-matching comparison points**: Identify every location in the codebase where an internally-constructed file path is compared against a user-supplied pattern (regex, glob, or substring match).
2. **Inspect path construction during traversal**: Trace how file paths are built during both recursive and non-recursive directory walking. Look for concatenation that introduces `./`, redundant separators, or platform-specific separators.
3. **Apply canonical normalization immediately before comparison**: Use the platform's normalization function (e.g., `os.path.normpath()`) on the file path at the comparison point itself — not at the point of discovery or at an intermediate processing step. This creates a single, reliable chokepoint.
4. **Ensure consistency across all code paths**: Verify that every traversal mode and every entry point that feeds paths into the matching logic applies the same normalization. Pay special attention to recursive vs. non-recursive modes, and to paths received from external tools vs. internally discovered paths.
5. **Add regression tests with non-canonical and platform-specific paths**: Create test cases that explicitly use paths with `./` prefixes, mixed separators, trailing slashes, and `..` segments to ensure the normalization holds under adversarial inputs.

### Why This Works

Normalizing at the comparison point rather than at discovery is the most robust approach because it establishes a **single invariant**: regardless of how many upstream code paths produce file paths, and regardless of what format those paths arrive in, they are always converted to canonical form before being tested against user patterns. This eliminates an entire class of bugs where a new traversal mode or a refactored path-construction step inadvertently introduces non-canonical paths. It also aligns the system's internal representation with the user's mental model — users write patterns based on canonical paths, and the system now guarantees it matches against canonical paths.

## Boundary Cases
- **Windows paths in regex patterns**: Users may write patterns with forward slashes, but `os.path.normpath()` on Windows converts to backslashes — the normalization must account for the direction of conversion or the regex must be adapted.
- **Symlinks and resolved vs. unresolved paths**: `normpath()` does not resolve symlinks; if the system sometimes resolves them and sometimes doesn't, paths may still diverge.
- **Paths with intentional `..` segments**: Normalization collapses `..`, which could change the semantic meaning if symlinks are involved (e.g., `a/symlink/../b` is not the same as `a/b` on the filesystem).
- **Root-relative vs. working-directory-relative paths**: A path like `./src/file.py` normalizes to `src/file.py`, but a user pattern anchored with `^./` would no longer match — documentation should clarify the canonical form.
- **Mixed inputs from external tools**: If the system also accepts file paths from external sources (e.g., command-line arguments, editor integrations), those paths may arrive in yet another format and must pass through the same normalization.

## PR Examples
- **pylint-dev__pylint-7080**: Recursive directory traversal produced non-normalized paths (containing `./` segments) that failed to match user-configured `--ignore-paths` regex patterns, causing ignore rules to silently have no effect during recursive linting.