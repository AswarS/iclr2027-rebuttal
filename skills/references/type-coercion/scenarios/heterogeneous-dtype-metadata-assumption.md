## Problem Description

When a validation or data conversion routine is designed to detect and warn about dtype changes during array conversion, it may silently fail for heterogeneous tabular inputs (e.g., pandas DataFrames). The routine assumes all array-like inputs expose type information through a single scalar `dtype` attribute, but tabular containers represent type metadata as a collection of per-column dtypes via a plural `dtypes` attribute. This mismatch causes the dtype-change detection logic to either retrieve a meaningless fallback value (e.g., `object`) or skip the check entirely, resulting in silent data loss when columns of mixed types are coerced into a single dtype without any user notification.

## Root Cause Analysis

The underlying principle is **homogeneity bias in abstraction design**. When developers build routines that accept "array-like" inputs, they naturally model type metadata as a single scalar `dtype` — which is correct for NumPy arrays and similar homogeneous containers. However, tabular containers like pandas DataFrames are also valid array-like inputs (they implement `__array__`) yet represent type information fundamentally differently: as a heterogeneous collection of per-column dtypes rather than a single scalar.

When the pre-conversion dtype capture step does `orig_dtype = input.dtype`, a DataFrame returns `dtype('O')` (object) regardless of its actual column types. The post-conversion comparison then sees `object != float64` (or similar) and either triggers a spurious warning or, worse, sees no meaningful difference and skips the warning entirely — even though significant type coercion (e.g., mixed int/string columns all becoming float) actually occurred. The implicit assumption that "one dtype describes the whole input" is the root of the failure.

## Solution Strategy

### 识别信号
- 观测到的现象: Silent data loss — heterogeneous tabular inputs are coerced to a single dtype without triggering the expected dtype-mismatch warning. Existing tests pass because they only cover homogeneous array inputs. No error is raised; the problem manifests as a missing validation message.

### 解决步骤
1. **Locate the pre-conversion dtype capture step** in the validation routine. Identify where `dtype` is read from the input before the array conversion call (e.g., `np.array()` or `np.asarray()`).
2. **Add a duck-typed branch for heterogeneous containers.** Check whether the input has both a `dtypes` (plural) attribute and an `__array__` method. This avoids hard-coding `isinstance(input, pd.DataFrame)` and keeps the solution library-agnostic.
3. **Store the full set of per-column dtypes** from the heterogeneous container before conversion (e.g., `set(input.dtypes)`).
4. **After conversion, compare the stored dtype set against the output array's scalar dtype.** If the set of original column dtypes is not equal to `{output.dtype}`, trigger the warning or corrective action. This correctly handles both uniform and mixed-type inputs.
5. **Format warning messages deterministically.** When reporting original dtypes, sort them (e.g., by string representation) so the message is stable across runs and easy to test.
6. **Add comprehensive test coverage:**
   - (a) Heterogeneous input where all columns already match the target dtype → no warning expected.
   - (b) Heterogeneous input where columns differ from the target dtype (uniform or mixed) → warning expected, message lists all original dtypes.
   - (c) Homogeneous array input → existing behavior preserved, no regressions.

### Why This Works

Set comparison between the original per-column dtypes and the post-conversion scalar dtype is the correct generalization of the existing scalar-to-scalar comparison. For homogeneous inputs, the set is a singleton and the comparison degenerates to the original logic. For heterogeneous inputs, the set captures all column types, and any mismatch with the output dtype is detected. Duck-typing (`hasattr(X, 'dtypes') and hasattr(X, '__array__')`) correctly identifies the relevant input category without coupling to any specific library, maintaining the routine's generality.

## Boundary Cases
- **DataFrame where all columns share the same dtype that matches the output dtype** — no warning should be emitted; the set comparison yields `{target_dtype} == {target_dtype}`.
- **DataFrame where all columns share the same dtype but it differs from the output dtype** — warning should be emitted; behaves like the homogeneous case but via the heterogeneous code path.
- **DataFrame with mixed dtypes (e.g., int64 and float64 columns)** — warning should list all unique original dtypes sorted deterministically.
- **Input that has a `dtypes` attribute but is not truly tabular** (e.g., a custom object) — the `__array__` guard prevents false positives.
- **Input with no `dtype` attribute at all** — the existing fallback (skip the check) should still apply; the new branch must not introduce new exceptions.
- **Sparse or extension dtype columns in a DataFrame** — the set of dtypes may include non-NumPy types; ensure string formatting handles these gracefully.

## PR Examples
- scikit-learn__scikit-learn-10949