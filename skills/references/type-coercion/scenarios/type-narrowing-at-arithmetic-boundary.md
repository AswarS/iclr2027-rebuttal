## Problem Description

When a numeric processing pipeline performs arithmetic operations (subtraction, division, normalization) on values that have passed through a type-conversion or unit-conversion step, certain "technically numeric" types—such as booleans, unsigned integers, or custom numeric wrappers—may survive the conversion unchanged yet fail at the arithmetic stage. The conversion step acts as a no-op for types already classified as numeric, silently forwarding values that lack full arithmetic operator support (e.g., NumPy booleans support bitwise XOR but not subtraction). This results in unexpected `TypeError` crashes deep inside the pipeline, far from the point where the type ambiguity was introduced.

## Root Cause Analysis

The underlying principle is a **semantic gap between type classification and operator capability**. Many pipelines use a broad "is numeric" check to decide whether data can flow into quantitative processing. Conversion or unit-normalization steps then assume they have produced standard arithmetic-capable values. However, these conversion functions are often identity operations for types that already belong to the numeric category—booleans, for instance, are a subtype of integers in NumPy and Python, so they pass numeric checks and survive conversion untouched.

The cognitive trap is the implicit assumption that **"successfully classified and converted" implies "fully arithmetic-capable."** Developers mentally model the conversion boundary as a normalizing funnel, but it is actually a pass-through for edge-case types. The mismatch only surfaces downstream when a subtraction, division, or other operator is invoked on a type that doesn't support it, producing a `TypeError` that is difficult to trace back to the real cause: an insufficiently narrow type guarantee at the conversion boundary.

## Solution Strategy

### 识别信号
- 观测到的现象: `TypeError` at a subtraction, division, or normalization operation on values that were expected to be plain numbers—especially involving boolean arrays or other restricted-arithmetic types.
- The error occurs **after** a type/unit conversion step that appeared to succeed without complaint.
- Input data uses edge-case numeric types (booleans, unsigned integers, custom numeric wrappers) that pass `is_numeric` checks but lack full operator support.

### 解决步骤
1. **Locate the boundary** between type/unit conversion and the first arithmetic computation in the pipeline. Trace the `TypeError` stack trace backward to find where the offending value was last transformed (or passed through unchanged).
2. **Audit the conversion step's output guarantees.** Determine whether the conversion function can return types that do not support the full set of downstream arithmetic operators (subtraction, division, multiplication). Pay special attention to identity/no-op paths for types already in the target category.
3. **Insert an explicit type-narrowing cast** (e.g., `float(x)` or `np.asarray(x, dtype=float)`) at the **narrowest point**—immediately after conversion and immediately before the first arithmetic operation. Do **not** change upstream classification logic or downstream arithmetic.
4. **Prefer casting at the point of use** over casting at data ingestion. Casting too early can alter dtype-dependent behavior in other pipeline stages (e.g., scale selection, categorical handling, display formatting).
5. **Add test coverage** for edge-case input types (booleans, unsigned integers, custom numeric wrappers) flowing through the complete pipeline to the arithmetic stage, verifying that no `TypeError` is raised and that results are numerically correct.

### Why This Works

Applying the cast at the narrowest point—right before arithmetic—establishes the **exact invariant** that the arithmetic code requires (standard float semantics) without disturbing any upstream logic that may depend on the original dtype. It converts the implicit assumption ("conversion output is arithmetic-capable") into an explicit guarantee. This is the most defensive and least invasive fix because:

- It doesn't alter how data is classified, routed, or stored elsewhere in the pipeline.
- It handles all current and future edge-case numeric types in a single, localized change.
- It makes the type contract visible in the code, reducing the chance of regression.

## Boundary Cases
- **Boolean arrays/columns:** Classified as numeric (subtype of integer), pass conversion unchanged, but NumPy booleans do not support subtraction (`True - True` raises `TypeError` in some contexts or produces unexpected results).
- **Unsigned integer types:** May underflow silently on subtraction (e.g., `uint8(3) - uint8(5)` wraps around), producing incorrect normalization results rather than a crash.
- **Custom numeric wrappers / extension dtypes:** Third-party or pandas extension types (e.g., `Int64`, `Float64` nullable types) that pass numeric checks but may not support all NumPy arithmetic operations natively.
- **Mixed-type Series after conversion:** A conversion step that returns the original object when it's "already numeric" may preserve a pandas Series with an unexpected dtype, causing downstream NumPy operations to fail.

## PR Examples
- mwaskom__seaborn-3190