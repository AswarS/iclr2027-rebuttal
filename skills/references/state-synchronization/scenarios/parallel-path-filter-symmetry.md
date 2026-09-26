## Problem Description

When a composite system processes inputs through multiple parallel sub-components and then merges their outputs, two or more parallel data paths are constructed from the same set of sub-components — one for the actual data and another for metadata (e.g., feature names, column labels, indices). If one path applies filtering logic that excludes degenerate/zero-output sub-components while the other path naively includes all sub-components (including those producing empty output), the two paths fall out of alignment. Any attempt to zip, merge, or index across these mismatched lists corrupts the pairing of data to metadata for all elements following the first discrepancy.

## Root Cause Analysis

The fundamental issue is a **symmetry-breaking implicit assumption**: the developer assumes that every configured sub-component will always produce at least one output element. Under this assumption, both paths naturally have the same length, so no explicit synchronization is needed. However, when a sub-component legitimately produces zero output columns (e.g., an empty feature selection, a transformer that drops all columns), one path — typically the data path — already handles this by skipping unfitted or empty-output components (often for architectural reasons, such as unfitted components being unable to generate metadata). The other path, built independently, iterates over all components without the same guard. This creates a length mismatch between the two parallel lists, and since elements are aligned positionally, a single missing element shifts all subsequent pairings, leading to crashes or silently corrupted state.

This is a specific instance of the broader **parallel-path filter symmetry** problem: whenever two collections are derived from the same logical source but constructed with different inclusion predicates, positional alignment is destroyed by any element that passes one predicate but not the other.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash/Exception**: `ValueError` or `IndexError` when merging outputs — list lengths don't match, or zipping produces unexpected pairings
  - **Inconsistent State**: Feature names or metadata labels are misaligned with actual data columns after a parallel merge operation
  - The failure only manifests when at least one sub-component produces zero output (empty selection, all-columns-dropped, etc.) — the happy path with all non-empty outputs works fine

### 解决步骤
1. **Map all parallel data paths**: Identify every list or sequence that is constructed by iterating over the same set of sub-components. Typically one path collects transformed data arrays and another collects metadata (names, labels, types, indices).
2. **Compare filtering predicates**: For each path, determine the inclusion criteria — does it skip sub-components that are unfitted, that produce zero columns, or that meet some other degenerate condition? Document the predicate for each path explicitly.
3. **Locate the asymmetry**: Find the path(s) where the filtering predicate differs. The bug is the path that includes zero-output components when the other path excludes them (or vice versa).
4. **Apply symmetric filtering**: Add the missing filter condition to the less-constrained path so both paths use equivalent inclusion logic. Prefer modifying the path that currently lacks filtering rather than removing filtering from the path that already has it, since the existing filter typically exists for sound architectural reasons.
5. **Validate with a zero-output test case**: Write a test where at least one sub-component is explicitly configured to produce zero output columns. Verify that the merged output structure (data + metadata) is internally consistent and that no crash occurs.

### Why This Works

By ensuring both parallel paths apply the same inclusion predicate, every element in one list has a corresponding element at the same index in the other list. The positional alignment contract is restored. This is the minimal fix because it doesn't require restructuring the iteration pattern or introducing explicit key-based pairing — it simply ensures the two paths agree on which sub-components are "present" in the output.

## Boundary Cases

- **All sub-components produce zero output**: Both paths should result in empty lists of equal length; the merge should produce a valid empty output structure rather than crashing.
- **A single sub-component in the pipeline produces zero output**: The most common trigger — the asymmetry causes an off-by-one that shifts all subsequent metadata assignments.
- **Multiple non-contiguous sub-components produce zero output**: The misalignment compounds, potentially causing more dramatic corruption or different exception types than the single-empty case.
- **Sub-components that produce zero output on some inputs but not others** (data-dependent emptiness): The bug may appear intermittently, making it harder to diagnose — tests should cover both the empty and non-empty cases for the same pipeline configuration.
- **Nested composite transformers**: If a sub-component is itself a composite that contains empty sub-components, the filtering symmetry must hold at every nesting level.

## PR Examples

- scikit-learn__scikit-learn-25570