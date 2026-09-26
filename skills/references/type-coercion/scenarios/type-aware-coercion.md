## Problem Description

When a function accepts array-like inputs and uses a naive array cast (e.g., `np.asarray()`) to normalize them before performing type-based dispatch, inputs that carry semantic type information through extension type systems (e.g., pandas nullable `Int64`, `Float64`, `boolean`) lose that type metadata during coercion. The naive cast silently degrades rich extension types into a generic fallback dtype (typically `object`), causing downstream type-dispatch logic to misclassify semantically numeric or boolean data as untyped, mixed-type, or unsupported. This manifests as unexpected errors (e.g., "mixed types," "unknown type") that only appear when data is passed through certain container representations (like pandas DataFrames with nullable dtypes), while identical data in standard NumPy arrays works correctly.

## Root Cause Analysis

Modern data containers increasingly use extension type systems where numeric/boolean type information is stored in dtype metadata rather than in the raw memory layout that low-level casts understand. A call like `np.asarray()` only understands the built-in NumPy type hierarchy — when it encounters an extension dtype it cannot map, it falls back to `object` dtype. Downstream code that branches on `dtype.kind` (e.g., checking for `'f'`, `'i'`, `'b'`) then sees `'O'` (object) and takes the wrong path.

The fundamental principle violated is: **when downstream logic depends on the resulting dtype for correctness, the conversion step must be the most type-aware conversion available**, not the lowest-level one. The implicit assumption that "all array-like containers will carry their numeric type through a simple cast" breaks when extension types encode equivalent semantic information through a different representation layer.

A secondary trap emerges during the fix: replacing a naive cast with a richer, validation-aware utility may introduce new error paths. If the original code had broad `except` clauses designed to handle ragged/irregular inputs by falling back to `object` dtype, those same handlers can now accidentally swallow intentional validation errors (e.g., rejection of complex-valued data) raised by the smarter utility. The exception handling contract changes when the conversion mechanism changes.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Semantically numeric inputs raise errors about "mixed types," "unknown types," or "unsupported types," but **only** when passed through specific container representations (e.g., pandas DataFrame/Series with nullable extension dtypes).
  - The same data in standard NumPy arrays or non-nullable pandas dtypes works without issue.
  - Intermediate inspection reveals the coerced array has `dtype=object` when it should have a numeric or boolean dtype.
  - The failure occurs at a type-dispatch boundary — code that inspects `dtype.kind` or uses dtype to select a processing path.

### 解决步骤
1. **Audit coercion sites**: Identify all code paths where raw array coercion (`np.asarray`, `np.array`, or equivalent) is applied to user-provided array-like inputs immediately before type-based branching or classification logic.
2. **Replace with type-aware conversion**: Substitute the naive cast with a validation-aware conversion utility that understands extension type systems and maps them to their canonical primitive equivalents (e.g., nullable `Int64` → `int64`, nullable `Float64` → `float64`, nullable `boolean` → `bool`). Use the highest-level conversion utility available in the codebase (e.g., `check_array` in scikit-learn) that already contains this mapping logic.
3. **Audit exception handlers**: Inspect every `try/except` block surrounding the old conversion. If a broad `except (TypeError, ValueError)` clause existed to handle ragged or irregular inputs, narrow it: examine error messages or error subtypes to distinguish between conversion failures (which should fall back gracefully) and intentional validation rejections (which must propagate). Re-raise errors that represent deliberate rejection of invalid data (e.g., complex-valued inputs).
4. **Add extension-type test coverage**: Write test cases for all relevant extension type variants (`Int8`–`Int64`, `Float32`–`Float64`, `boolean`, and their `UInt` counterparts) to verify they produce identical downstream behavior as their non-nullable equivalents.

### Why This Works

Extension type systems encode equivalent semantic information (numeric, boolean) through a representation layer that naive casts discard. A validation-aware conversion utility already contains the mapping logic to normalize these extension types to their primitive equivalents, avoiding duplication of dtype-resolution logic and ensuring all equivalent type representations converge to the same canonical form before type-dispatch occurs. Auditing exception handlers ensures that the richer conversion path does not introduce silent error swallowing — the error-handling contract is updated to match the new conversion semantics.

## Boundary Cases
- **Nullable types with actual `NA` values**: Converting nullable extension types with missing values to non-nullable NumPy dtypes requires choosing a float representation (since NumPy integers cannot represent NaN). Ensure the conversion utility handles this promotion correctly.
- **Mixed-column DataFrames**: A DataFrame where some columns use extension dtypes and others use standard dtypes — each column's coercion must be handled independently.
- **Complex-valued inputs**: A richer conversion utility may explicitly reject complex numbers. If the old broad `except` clause silently converted these to `object`, the new path must still raise the appropriate error rather than swallowing it.
- **Ragged/irregular array-like inputs**: The original fallback to `object` dtype for genuinely ragged inputs (e.g., lists of different-length lists) must still work — only the extension-type case should change behavior.
- **Third-party extension types**: Libraries beyond pandas (e.g., PyArrow-backed dtypes) may introduce additional extension types. The solution should be extensible or delegate to a utility that tracks these evolving type systems.

## PR Examples
- scikit-learn__scikit-learn-25638