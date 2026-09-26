## Problem Description

This pattern occurs when a multi-step data transformation pipeline relies on a downstream cleanup mechanism (e.g., `squeeze`) to remove artifacts introduced by an earlier selection/indexing step, but the cleanup mechanism only covers a subset of the artifact forms that can actually appear. Specifically, when selecting along an axis introduces a coordinate, the developer assumes a later squeeze or reshape step will remove it. This holds true when the data has multiple dimensions — the artifact manifests as a size-1 dimension that squeeze can eliminate. However, when the source data has minimal dimensionality (e.g., a single dimension), the same selection produces a **scalar (zero-dimensional) coordinate** instead, which squeeze silently ignores. The orphaned coordinate then causes merge conflicts, duplicate key errors, or unexpected extra metadata when results are reassembled into a collection.

## Root Cause Analysis

The fundamental issue is a **mismatch between the artifact forms produced by a selection operation and the forms handled by the cleanup mechanism**. This stems from conflating two distinct concepts: **dimensions** and **coordinates**.

- A `squeeze` operation removes dimensions of size 1 but has **no effect** on scalar (zero-dimensional) coordinates.
- When data has ≥2 dimensions, indexing along one axis reduces that axis to size 1, creating a removable dimension — the "typical" case the developer had in mind.
- When data has exactly 1 dimension, indexing along that axis collapses it entirely, producing a scalar coordinate with zero dimensions. This coordinate is invisible to dimension-based cleanup.

The cognitive trap is an **implicit assumption** that the artifact will always take a dimensional form. The developer's mental model covers the common case but misses the edge case where dimensionality is minimal. This is an instance of the broader principle: **deferred cleanup is only safe if it covers the full range of artifact shapes that the producing step can generate**.

## Solution Strategy

### 识别信号
- 观测到的现象: Merge conflicts, duplicate key errors, or unexpected extra coordinates appear when reassembling extracted pieces into a collection — but **only** when the source data has fewer dimensions than the "typical" case (e.g., 1D instead of 2D+).
- A `squeeze` or reshape call exists downstream of a selection/indexing call, intended to clean up coordinates introduced by that selection.
- The bug is intermittent or data-shape-dependent, passing tests with higher-dimensional inputs but failing with minimal-dimensional inputs.

### 解决步骤
1. **Trace the artifact's origin**: Identify the exact selection/indexing operation that introduces the unwanted coordinate. Confirm that this coordinate is not part of the desired output.
2. **Audit the cleanup mechanism's coverage**: Check whether the downstream cleanup step (e.g., `squeeze`, `reshape`, `drop`) is guaranteed to remove the artifact in **all** dimensionality scenarios — including the scalar/zero-dimensional case.
3. **Eliminate the artifact at the source**: Instead of relying on deferred cleanup, use the selection operation's own artifact-prevention parameter. For example, if the API supports `drop=True` (or an equivalent flag that discards index coordinates), apply it directly on the selection call.
4. **Remove or simplify the now-redundant downstream cleanup**: If the artifact is no longer introduced, the squeeze/reshape step may be unnecessary or can be simplified. Retain it only if it serves other purposes.
5. **Verify across dimensionality boundaries**: Test with both the minimal-dimension case (1D / scalar result) and the general multi-dimension case (2D+) to confirm the fix handles all forms and introduces no regressions.

### Why This Works

Removing artifacts at the point of creation (**eager cleanup**) is strictly more robust than deferred cleanup because it eliminates the dependency on downstream steps correctly handling every possible artifact shape. The selection API's `drop` parameter is designed precisely for this purpose — it prevents the coordinate from ever being attached, regardless of whether the result is dimensional or scalar. This approach respects the principle that **cleanup logic must match the full range of artifact forms**, and the simplest way to guarantee that match is to never produce the artifact in the first place.

## Boundary Cases
- **Single-dimension input**: The primary edge case. Selection along the only dimension produces a scalar coordinate (0-dimensional) rather than a size-1 dimension, bypassing `squeeze` entirely.
- **Already-scalar input**: If the input data is itself scalar (0-dimensional), selection may be a no-op or may still attach index metadata that no dimensional cleanup can remove.
- **Multi-step chained selections**: When multiple sequential selections each introduce coordinates, a single downstream squeeze may remove some but not all, depending on which axes were collapsed versus retained.
- **Mixed-type collections**: When reassembling results from inputs of varying dimensionality (some 1D, some 2D+), only a subset of entries carry the orphaned coordinate, causing inconsistent schemas during merge.
- **Coordinate vs. dimension naming collisions**: The orphaned scalar coordinate may share a name with an existing coordinate in the target collection, triggering a conflict that would not occur if the artifact were properly removed.

## PR Examples
- **pydata/xarray#4094**: A selection operation during variable extraction introduced a coordinate that `squeeze` was expected to remove. With 1D input data, the coordinate became scalar and persisted, causing a merge conflict when reassembling a `Dataset`. The fix applied `drop=True` on the selection call itself, preventing the coordinate from being introduced regardless of input dimensionality.