## Problem Description

A build tool or code generator produces output artifacts in a flat directory structure, but the downstream consumer (e.g., a runtime discovery mechanism like `man`, `pkg-config`, or a module loader) expects artifacts organized into a specific subdirectory hierarchy dictated by a well-established convention. Because the generator's output layout violates the consumer's discovery contract, the artifacts are effectively broken by default — they cannot be found or used without manual reorganization, even though all the content is correct.

This is an **output-structure-consumer-convention mismatch**: the generator has all the metadata needed to produce the correct layout but simply omits one or more directory levels in its output path construction.

## Root Cause Analysis

The root cause is an **implicit assumption violation** in the generator's output logic. The generator treats its output directory as a flat namespace, writing all artifacts directly into a single target folder. However, the consumer's discovery protocol relies on a hierarchical directory convention (e.g., `man` searches for pages inside `man<section>/` subdirectories within each path on `MANPATH`). This convention is not optional or configurable on the consumer side — it is a fundamental part of how discovery works.

The mismatch persists because:

1. **The generator's output "works" in isolation** — the files are generated correctly, and users who manually copy or reference individual files never notice the structural defect.
2. **The convention is so well-established that it's invisible** — developers building the generator may not realize the consumer imposes directory structure requirements, or may assume a packaging/install step will handle reorganization.
3. **The metadata needed to construct the correct path already exists** within the generator (e.g., a section number, a category tag), but it is simply not used during output path construction.

The result is that the generator's output is structurally incompatible with the standard integration path, forcing every user to work around the defect.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Generated output files exist and have correct content, but the downstream consumer cannot discover or load them when pointed at the output directory.
  - Users report that setting a standard search path (e.g., `MANPATH`, `PKG_CONFIG_PATH`) to the build output directory does not work, despite the files being present.
  - Workarounds involve manually moving files into subdirectories or writing wrapper scripts to bridge the structural gap.
  - The issue manifests as **wrong output layout** rather than wrong content — a subtle but critical distinction.

### 解决步骤

1. **Identify the consumer's discovery contract**: Research and document the exact directory hierarchy the downstream consumer expects. Consult the consumer's documentation or specification (e.g., `man(1)` expects `man1/`, `man3/`, etc. subdirectories). This is the authoritative source of truth for what "correct output" means.

2. **Audit the generator's current output path construction**: Trace the code path from artifact metadata (e.g., section number, category) through to the final file write. Identify the exact point where the output path is assembled and confirm that the subdirectory component is missing.

3. **Modify the output path to include the required subdirectory**: Using metadata already available in the generator's context, insert the missing directory level into the output path. Add a directory-creation call (e.g., `os.makedirs(..., exist_ok=True)`) to ensure the subdirectory exists before writing. This is typically a 3–5 line change localized to the builder's write method.

4. **Make this the unconditional default behavior**: Do **not** introduce a configuration flag to toggle between the old flat layout and the corrected hierarchical layout. The flat layout was a bug relative to the consumer's well-established convention, not a legitimate alternative. Gating correctness behind a flag adds unnecessary configuration surface, delays the fix for most users, and implies the broken layout is supported.

5. **Validate against the consumer's discovery mechanism**: Test by pointing the consumer's search path at the build output directory and confirming that artifacts are now discoverable without manual intervention.

### Why This Works

The fix succeeds because it aligns the generator's output structure with the consumer's **non-negotiable discovery contract**. The consumer's directory convention is not a preference — it is the protocol by which artifacts are located at runtime. By correcting the output path at its source, every downstream integration path (development use, packaging, deployment) benefits automatically.

Making the fix unconditional is correct because the previous flat layout never satisfied the consumer's contract. There is no population of users who depend on the flat layout as a feature — they either work around it or don't use the direct-discovery integration path. The simplicity of the change (adding one path component and a directory-creation call) reflects the simplicity of the underlying defect: a missing directory level.

## Boundary Cases

- **Multiple consumers with conflicting conventions**: If the same output must serve consumers with different directory expectations, the generator may need a layout strategy selector. However, this is distinct from the single-consumer case where there is one correct layout.
- **Existing automation that hardcodes the flat path**: Some users may have scripts or CI pipelines that reference the old flat output paths. These scripts were already compensating for the bug; after the fix, they may need a one-time update. This is acceptable — preserving a broken default to avoid breaking workarounds is the wrong trade-off.
- **Artifacts without clear subdirectory metadata**: If some artifacts lack the metadata needed to determine their subdirectory (e.g., a document with no section number), the generator should fall back to a sensible default or emit a warning, rather than silently placing the artifact in the wrong location.
- **Cross-platform path conventions**: The subdirectory convention may vary across platforms (e.g., case sensitivity, separator characters). The fix should use platform-appropriate path construction (e.g., `os.path.join` or `pathlib.Path`).

## PR Examples

- **sphinx-doc__sphinx-8273**: Sphinx's `man` builder wrote all generated man pages into a flat output directory. The `man` utility expects pages organized into `man<section>/` subdirectories. The fix modified the builder's output path to include the section subdirectory, making `MANPATH` integration work out of the box without any configuration changes.