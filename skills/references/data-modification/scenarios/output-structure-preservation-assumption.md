## Problem Description

A post-processing wrapper or decorator layer unconditionally propagates structural metadata (e.g., row indices, shape-dependent labels, dimensional annotations) from the input onto the output of a transformation. This works correctly when the inner transformation preserves the cardinality and structure of the input (e.g., feature scaling, encoding), but causes crashes or data corruption when the inner transformation legitimately changes the output's structure relative to the input (e.g., aggregation, sampling, pivoting, filtering). The wrapper assumes structural invariance — that every transformation produces an output with the same row semantics as its input — and this implicit assumption breaks composability with a broad class of valid operations.

## Root Cause Analysis

The underlying principle violated is **output self-description authority**: when a transformation produces a rich, self-describing container (e.g., a DataFrame with its own index and shape), that container's metadata is authoritative. A generic wrapper has no business overriding it with metadata derived from the input, because the wrapper cannot know whether the transformation preserved, reduced, expanded, or entirely restructured the observation dimension.

This is an instance of the **implicit assumption violation** pattern. The wrapper was designed with the common case in mind — transformations that map N input rows to N output rows — and encoded that assumption as an unconditional metadata copy. The assumption was never explicitly documented or guarded, so it silently became a contract that all pluggable inner operations were expected to satisfy. When a user supplies a many-to-one (aggregation) or one-to-many (upsampling) operation, the contract is violated, and the system crashes with a length-mismatch or shape-mismatch error at the metadata assignment step.

The cognitive trap is **assuming structural invariance by default** rather than **detecting structural invariance before acting on it**.

## Solution Strategy

### 识别信号
- 观测到的现象: A length-mismatch or shape-mismatch exception is raised when the wrapper attempts to assign input-derived row indices or dimensional labels onto a transformation output that has a different number of rows than the input. This typically manifests as a `ValueError` (e.g., "Length of values does not match length of index") during the metadata propagation step, not during the transformation itself.

### 解决步骤
1. **Locate the unconditional metadata propagation layer.** Find the post-processing code path (wrapper, decorator, or pipeline step) that copies structural metadata — specifically row-level metadata such as indices, row labels, or observation-level annotations — from the input container onto the output of the inner transformation.

2. **Add a conditional guard based on output container type.** Before applying input-derived structural metadata, check whether the output is already a rich, self-describing container (e.g., a pandas DataFrame or Series). If it is, its metadata is authoritative — skip the structural metadata propagation entirely for that output.

3. **Preserve non-structural metadata propagation.** Continue to apply metadata that does not depend on row cardinality, such as column names, feature labels, or dtype annotations. These are naming conventions that remain valid regardless of whether the output's row count matches the input's.

4. **Validate both invariant and non-invariant cases.** Ensure the fix handles: (a) transformations that preserve input structure (the wrapper's metadata is redundant but skipping it is harmless, since the output already carries equivalent metadata), and (b) transformations that change output structure (the wrapper's metadata would be incorrect and is correctly skipped).

5. **Add regression tests for structure-changing transformations.** Write test cases using inner operations that perform aggregation (many-to-one), filtering (subset of rows), upsampling (one-to-many), and pivoting (reshape) to ensure the wrapper does not crash or corrupt metadata for any of these categories.

### Why This Works

A rich output container is self-describing: its index, shape, and row labels are determined by the transformation that produced it, not by the input that was fed into the transformation. By deferring to the output's own metadata when it exists, the wrapper respects the **principle of output authority** — the transformation, not the caller, defines the semantics of its result. This restores composability: any transformation, regardless of whether it preserves input cardinality, can be safely wrapped without triggering metadata conflicts.

## Boundary Cases
- **Output is a raw array (not a rich container).** The wrapper should still apply input-derived metadata in this case, since the raw array carries no metadata of its own and the wrapper's propagation is the only way to annotate it. The conditional guard must distinguish between self-describing containers and raw numeric arrays.
- **Output is a DataFrame but happens to have the same number of rows as the input.** The fix should still skip overwriting, because same-length does not imply same-row-semantics (e.g., a groupby that produces the same number of groups as input rows). The check should be based on container type, not on length equality.
- **Output is a DataFrame with a default (RangeIndex) index.** Even in this case, the output's index is authoritative — it was set by the transformation. Overwriting it with the input's potentially non-default index would be incorrect if the row semantics differ.
- **Chained or nested wrappers.** If multiple wrapper layers each attempt metadata propagation, the innermost wrapper's decision to skip propagation must be respected by outer layers. Each layer should independently check whether the output is already self-describing.

## PR Examples
- scikit-learn__scikit-learn-25747