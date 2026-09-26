## Problem Description

When a system allows optional components in a collection to be disabled via a sentinel value (e.g., setting an entry to `None`, `"drop"`, or similar), every code path that iterates over that collection must consistently handle the disabled state. A common failure pattern occurs when the **main processing loop** correctly skips disabled entries, but **auxiliary loops** — such as validation, capability-checking, or pre-processing loops — do not. These auxiliary loops attempt attribute access on the sentinel value, causing a crash (typically `AttributeError`). This is a **validation-guard consistency** problem: guards that protect against disabled components are applied inconsistently across iteration sites over the same collection.

## Root Cause Analysis

The root cause is **symmetry-breaking** between multiple iteration sites over a shared collection of optional components. The system establishes a convention for disabling components (e.g., setting them to `None`), and the primary processing loop respects this convention with a guard clause. However, auxiliary loops — often added later, by different authors, or as separate concerns like validation or feature inspection — are written independently and fail to replicate the same guard.

This is an instance of the broader principle that **invariants about collection contents must be enforced uniformly at every access site**. When the sentinel-handling logic is duplicated rather than centralized, each new iteration site becomes an opportunity to forget the check. The bug is latent: it only manifests when a user actually disables a component and then triggers the unguarded code path (e.g., calling a method that checks component capabilities), making it easy to miss in initial development and testing.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `AttributeError` or `TypeError` when accessing methods/attributes on a `None` (or other sentinel) value within a loop over a component collection.
  - The crash occurs in a validation, capability-checking, or pre-processing loop — not in the main processing loop.
  - The error is triggered only when a component has been explicitly disabled (set to sentinel) and a secondary code path is invoked.
  - The main processing loop already contains a guard clause (e.g., `if component is None: continue`) that the failing loop lacks.

### 解决步骤
1. **Locate the sentinel-handling pattern** in the main processing loop. Identify the exact guard clause used (e.g., `if transformer is None: continue`, `if estimator == "drop": continue`).
2. **Search exhaustively for all iteration sites** over the same collection. Use grep/search for the collection variable name and any loop constructs (`for ... in ...`) that reference it. Include validation loops, capability checks, logging, serialization, and any other auxiliary code paths.
3. **Audit each iteration site** to verify it handles the sentinel/disabled state identically to the main loop. Flag any site that accesses component attributes or methods without first checking for the sentinel.
4. **Add the guard clause** at the top of each unguarded loop body, before any attribute access. Ensure the guard is identical in semantics to the one in the main loop (same sentinel value, same skip behavior).
5. **Consider centralizing the filtering** by introducing a shared helper method or property (e.g., `_active_components()`) that pre-excludes disabled entries. Refactor all iteration sites to use this accessor instead of iterating over the raw collection directly. This eliminates the possibility of future iteration sites forgetting the check.
6. **Add regression tests** that disable one or more components and then exercise every public method that triggers iteration over the collection, ensuring no crashes occur.

### Why This Works

By ensuring every iteration site applies the same guard — or better, by centralizing the filtering so individual sites cannot forget — the system uniformly respects the convention for disabled components. The sentinel value is never dereferenced, and the invariant ("disabled entries are skipped before attribute access") holds across all code paths. Centralization via a shared accessor converts a distributed, error-prone obligation into a single point of enforcement.

## Boundary Cases
- **All components disabled**: When every entry in the collection is set to the sentinel value, loops should gracefully handle an empty effective collection (no iterations, no errors, possibly a meaningful no-op or warning).
- **Mixed sentinel types**: If the system supports multiple ways to disable a component (e.g., both `None` and `"drop"`), all guard clauses must check for all sentinel forms consistently.
- **Dynamic disabling after construction**: Components disabled after initial setup (e.g., via `set_params`) may bypass constructor-time validation. Ensure guards are in runtime loops, not just in `__init__`.
- **Nested collections**: If components themselves contain sub-collections with their own sentinel conventions, the guard pattern must be applied recursively at each nesting level.
- **Serialization and cloning**: Code paths that serialize, clone, or deep-copy the collection (e.g., `get_params`, `__repr__`) must also handle sentinel values without attempting attribute access.

## PR Examples
- scikit-learn__scikit-learn-13779: A `ColumnTransformer` validation loop checking whether transformers support `get_feature_names` did not skip transformers set to `"drop"`, causing an `AttributeError`. The main `_fit` loop already handled this case correctly.