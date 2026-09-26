## Problem Description

When a processing pipeline decomposes composite data structures into atomic parts (e.g., splitting a product into individual factors, expanding nested collections into flat elements) and then emits results, it may violate an output contract that requires entries to be consolidated by a shared grouping key. The decomposition step can produce multiple items that map to the same key, but if no re-aggregation step exists before output, the result contains duplicate grouping keys where the contract guarantees uniqueness. This is a **decomposition-reaggregation mismatch**: the pipeline breaks things apart but never puts them back together in the way the output format demands.

## Root Cause Analysis

The fundamental issue is an **asymmetry between decomposition and aggregation**. When a pipeline splits composite inputs into finer-grained parts, it implicitly destroys any grouping structure that existed in the original data. If the output contract requires grouped results (at most one entry per key, with values combined), the pipeline must include an explicit consolidation step to restore that invariant.

The cognitive trap is subtle: developers model the pipeline as a simple **map** operation (input → process → output) when it actually requires a **map-reduce** pattern (input → decompose → process → group-by-key → combine → output). The grouping step is invisible during development because typical test cases produce at most one item per group. The bug only surfaces when an input generates multiple atomic parts that share the same grouping key — a case that is easy to overlook because it depends on the specific structure of the input, not on the processing logic itself.

This is an implicit assumption violation: the code assumes that decomposed parts will naturally have distinct grouping keys, but nothing in the decomposition logic enforces this.

## Solution Strategy

### 识别信号
- 观测到的现象: Output contains **multiple entries with the same grouping key** where the contract specifies at most one entry per key (wrong output / inconsistent state).
- Results appear "duplicated" or "split" in a way that doesn't match the expected consolidated format.
- The bug is input-dependent — it only manifests when composite inputs decompose into multiple parts sharing a key.

### 解决步骤
1. **Identify the output contract's grouping invariant.** Determine what property must be unique across output entries and how items sharing that property should be combined (e.g., factors multiplied, counts summed, lists concatenated).
2. **Trace the decomposition path.** Locate where the pipeline splits composite inputs into atomic parts (recursive flattening, argument expansion, factor enumeration, etc.) and verify whether this can produce multiple results with the same grouping key.
3. **Choose a fix strategy:**
   - **(a) Remove unnecessary decomposition** — if the composite structure already represents the correct grouping, stop breaking it apart. This is the simplest fix when the decomposition adds no value.
   - **(b) Add an explicit post-processing consolidation step** — group results by the required key and merge them using the appropriate combining operation. This is necessary when the decomposition serves a legitimate purpose for intermediate processing.
4. **Scope the fix carefully.** Gate the consolidation logic on the specific output mode or method that requires it, to avoid affecting other code paths that legitimately need the flat enumeration.
5. **Add regression tests** that exercise inputs producing multiple items with the same grouping key, ensuring consolidation is verified.

### Why This Works

Decomposition and re-aggregation must be **symmetric**: if a pipeline breaks apart composite structures, it must restore any grouping invariants required by the output contract before emitting results. Without this symmetry, the decomposition is lossy with respect to the grouping property. By explicitly consolidating results before output, the pipeline completes the map-reduce cycle and satisfies the contract regardless of how many atomic parts share a key.

## Boundary Cases
- **Single-element groups**: When every decomposed part maps to a unique key, the bug is invisible — consolidation is a no-op. Tests must include multi-element groups to catch the mismatch.
- **Identity combining operations**: If the combining operation has an identity element (e.g., multiplying by 1, summing 0), ensure that the consolidation step handles the single-item case without altering the result.
- **Nested decomposition**: Recursive flattening may produce grouping-key collisions at multiple levels. The consolidation step must run after all levels of decomposition are complete, not just the first.
- **Mixed output modes**: Some code paths may legitimately want flat enumeration while others require grouped output. The consolidation must be applied selectively to avoid breaking the flat-output paths.
- **Empty or trivial inputs**: Ensure the consolidation step handles empty decomposition results and single-element inputs gracefully without introducing off-by-one errors or empty groups.

## PR Examples
- **sympy__sympy-18698**: A function decomposed products into individual factors and emitted results without re-aggregating factors that shared the same base, producing duplicate entries in an output format that required consolidated (base, exponent) pairs.