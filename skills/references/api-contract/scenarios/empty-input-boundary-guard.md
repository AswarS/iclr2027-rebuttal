## Problem Description

When a high-level API accepts variably-sized collections (arrays, lists, batches) and delegates processing to a lower-level library (C extension, external service, internal engine), the lower-level component often has stricter or undocumented constraints on minimum input size. The high-level API's contract logically permits zero-length inputs — they satisfy all structural requirements (correct dimensionality, matching lengths across arguments) — but the delegate implicitly requires at least one data element. This gap between the public API's accepted domain and the delegate's actual capabilities causes cryptic, misleading errors (e.g., dimension mismatch, type inconsistency) when empty but structurally valid inputs are passed through.

This is a specific instance of the **leaky abstraction** pattern: an abstraction layer fails to fully insulate callers from the limitations of its underlying implementation, and the leak manifests specifically at the **zero-cardinality boundary** — the degenerate case where all structural invariants hold but no actual data elements exist.

## Root Cause Analysis

The fundamental issue is a **domain mismatch between abstraction layers**. The public API defines its contract in terms of structural validity (correct number of dimensions, matching axis lengths, proper dtypes), and zero-length input satisfies all of these constraints. However, the lower-level library defines its operational domain in terms of minimum cardinality — it assumes at least one element exists to operate on. This assumption is rarely documented and never enforced with a clear error message.

The cognitive trap is straightforward: developers validate structural properties (shape, dtype, dimensionality) and assume that if inputs pass all explicit checks, the downstream computation will handle them correctly. Zero-length is a degenerate cardinality that lives in the gap between the API's structural contract and the delegate's implicit minimum-size requirement. Whenever an abstraction layer delegates to a component with a narrower accepted domain, the abstraction **must** guard the boundary cases that fall in that gap — otherwise the abstraction leaks.

## Solution Strategy

### 识别信号
- 观测到的现象: Passing an empty but structurally valid input (e.g., empty array with correct dimensionality, empty list, zero-row batch) to a public API raises an unexpected low-level error — such as a dimension mismatch, type error, or segfault — rather than returning an empty result of matching structure.
- The error message is cryptic and references internals of the delegate library, not the public API's domain language.
- The failure is a regression on edge cases: it works for any non-empty input but breaks specifically at zero elements.

### 解决步骤
1. **Locate the dispatcher chokepoint**: Identify the central adapter or dispatcher layer that sits between the public API surface and the lower-level library — the narrowest funnel through which all calling conventions pass before reaching the delegated function.
2. **Enumerate input-path variants**: Within the dispatcher, identify all distinct input-normalization paths (e.g., one path for multiple 1-D arrays, another for a single N-D array, another for keyword-based argument packing).
3. **Add early-return guards for zero-length input**: In each input-normalization path, insert a guard that checks whether the input has zero elements along the data axis. When zero-length input is detected, return empty output arrays with the **same shape and dtype** as the input, preserving the contract that output structure mirrors input structure. Do **not** forward the call to the lower-level library.
4. **Ensure full coverage across all paths**: Verify that the guard covers every input-path variant in the dispatcher so that all downstream public methods routing through it inherit the fix without per-method duplication.
5. **Add regression tests**: Write tests for each calling convention with empty inputs (empty 1-D arrays, zero-row 2-D arrays, empty lists) to lock in the expected behavior and prevent future regressions.

### Why This Works
- **Chokepoint guarding** fixes all downstream public methods simultaneously, following the DRY principle and ensuring consistent behavior across the entire API surface without per-method patches.
- **Returning empty arrays of matching shape** is the least-surprising behavior: it preserves the invariant that output structure mirrors input structure, which is critical for callers processing dynamically-sized batches that may legitimately be empty (e.g., filtering pipelines, streaming processors, conditional batch operations).
- **Not forwarding to the delegate** eliminates the domain mismatch entirely — the abstraction layer absorbs the boundary case that the delegate cannot handle, fulfilling its role as a complete insulation layer.

## Boundary Cases
- **Zero-length 1-D array**: A single empty array `[]` passed where a list of values is expected. Must return an empty array of the same dtype, not raise an error.
- **Zero-row N-D array**: A 2-D array with shape `(0, K)` where K matches the expected column count. Must return output with shape `(0, M)` where M is the expected output column count.
- **Multiple empty arrays as separate arguments**: When the API accepts multiple parallel arrays (e.g., coordinates), all empty but with matching zero-lengths. Must return corresponding empty outputs for each.
- **Mixed empty and non-empty inputs**: If the API accepts independent batches, ensure that empty batches produce empty outputs while non-empty batches are processed normally — the guard should be per-batch, not global.
- **Dtype preservation**: The returned empty arrays must carry the correct dtype (e.g., float64, not object) so that downstream consumers relying on dtype do not break.

## PR Examples
- astropy__astropy-7746