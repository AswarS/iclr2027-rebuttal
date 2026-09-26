## Problem Description

When values from one typed container are assigned into another typed container, the target container's capacity constraints (e.g., fixed-width string length, integer bit-width) may be insufficient to hold the source values. This occurs because typed arrays infer their dtype and capacity from their *original* contents at construction time, not from the full range of values that may later be written into them. The result is silent data truncation or corruption — values are clipped to fit the target's constraints without any error at the point of assignment, leading to mysterious failures downstream (e.g., "unseen labels," mismatched lookups, or validation errors on data that *should* be present).

This pattern is especially insidious with fixed-width string arrays (e.g., NumPy `<U3` vs `<U10`), where assigning a 10-character string into a `<U3` array silently produces a 3-character truncated string. But the principle generalizes to any scenario where a typed buffer's constraints are derived from initial data and later must hold values from a differently-constrained source.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation**: developers treat a copy of a typed array as a general-purpose mutable container, assuming that reading a value from source array A and writing it into target array B will preserve the value faithfully. However, typed array systems enforce capacity constraints that are *structurally embedded* in the container's dtype, not checked dynamically at assignment time.

The root cause chain is:

1. **Target array dtype is inferred from original contents** — e.g., an array of short strings gets dtype `<U3`.
2. **Source array (or lookup table) contains values with larger capacity requirements** — e.g., replacement labels are longer strings with dtype `<U10`.
3. **Assignment proceeds without dtype compatibility check** — the language/library silently truncates or overflows the value to fit the target's constraints.
4. **No error is raised at the point of mutation** — the corruption is invisible until downstream code encounters the mangled value and fails with a seemingly unrelated error.

The cognitive trap is that assignment *appears* to succeed. The feedback loop between cause (truncation at write) and effect (failure at read) is broken, making this class of bug extremely difficult to diagnose.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Downstream validation raises errors about "unseen labels" or values that should exist but are not found
  - String values appear truncated (trailing characters missing) after a substitution or mapping operation
  - Silent data loss — no exception at the point of assignment, but data integrity is compromised
  - Crashes or exceptions in code that consumes transformed data, not in the transformation itself
  - The bug manifests only when replacement values are *longer/larger* than original values; shorter replacements work fine

### 解决步骤

1. **Identify every code path where a value from one typed container is assigned into another typed container**, especially when the source and target containers were constructed independently (e.g., a copy of input data receiving values from a separately-built lookup table or encoder mapping).

2. **Compare the dtype or capacity constraints of the target container against the source container.** Specifically check whether the target's `itemsize` (or equivalent width/precision constraint) is smaller than the source's. For NumPy arrays, compare `target.dtype.itemsize` vs `source.dtype.itemsize`; for fixed-width strings, compare the character width (e.g., `<U3` vs `<U10`).

3. **Conditionally upcast the target container's dtype before performing substitution.** When the source dtype has a larger capacity than the target dtype, cast the target array to the source's dtype (e.g., `target = target.astype(source.dtype)`) *before* writing any values. This ensures the target can hold all possible replacement values without truncation.

4. **Prefer casting to the specific required dtype rather than a generic unconstrained type.** For example, use the exact fixed-width string dtype from the source (`<U10`) rather than falling back to `object` dtype. This preserves memory layout and performance characteristics of the typed array.

5. **Only apply the cast when necessary.** When dtypes are already compatible or the target's capacity is already sufficient (target itemsize ≥ source itemsize), skip the cast to avoid unnecessary memory overhead and array reallocation.

### Why This Works

Casting the target to the source's dtype before assignment guarantees sufficient capacity because the replacement values *originated* from that dtype — it is a minimal, precise, and provably correct bound on the required capacity. This approach:

- **Eliminates silent truncation** by ensuring the container can hold any value it will receive.
- **Preserves type specificity** by using the exact required dtype rather than a lossy fallback (like `object`).
- **Minimizes overhead** by only recasting when a genuine mismatch is detected.
- **Addresses the root cause** (capacity mismatch) rather than the symptom (downstream validation failure).

## Boundary Cases

- **Equal-capacity dtypes**: When source and target have the same itemsize/dtype, no cast is needed — the check should be a no-op to avoid unnecessary memory allocation.
- **Target is already larger than source**: If the target was constructed from data that already exceeds the source's capacity, no upcast is needed. The comparison must be directional (only upcast target when target < source).
- **Mixed-type containers (object dtype)**: If the target is already an `object` dtype array, it can hold arbitrary Python objects and no cast is needed. The check should handle this gracefully.
- **Non-string typed arrays**: The same pattern applies to integer overflow (e.g., `int8` target receiving `int32` values) or float precision loss (`float32` target receiving `float64` values). The solution generalizes: always compare capacity before cross-container assignment.
- **Multiple source arrays with different dtypes**: When replacement values come from multiple sources with varying dtypes, the target must be upcast to the *maximum* capacity across all sources.
- **Empty arrays or no replacements needed**: When no substitution actually occurs (e.g., all values already match), the upcast is unnecessary but harmless. The conditional check avoids this overhead.
- **Structured dtypes or record arrays**: Capacity mismatches can occur at the field level within structured arrays; each field must be checked independently.

## PR Examples

- **scikit-learn__scikit-learn-12471**: Label encoding with fixed-width string arrays where inverse-transformed labels were longer than the original encoded values, causing silent truncation in the output array and subsequent "unseen labels" validation errors.