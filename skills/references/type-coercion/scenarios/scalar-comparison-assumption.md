## Problem Description

When code compares values of unknown or heterogeneous types using `==` or `!=`, and the result is consumed in a scalar boolean context (e.g., `if`, `while`, ternary expressions, boolean operators), array-like types such as NumPy arrays, pandas Series, or custom objects with element-wise comparison semantics will return non-scalar results instead of a single boolean. This causes crashes (typically `ValueError: The truth value of an array is ambiguous`) or undefined behavior. The pattern most commonly surfaces in serialization layers, repr/display generation, configuration diffing, and parameter change detection — anywhere values are drawn from a broad parameter space that may include both scalars and composite types.

## Root Cause Analysis

The underlying principle is **scalar comparison universality assumption**: developers mentally model all values as scalars where `!=` and `==` yield a single `True` or `False`. This assumption is valid for Python built-in types (int, float, str, etc.) but breaks when the value space includes composite types that overload comparison operators to return element-wise results. NumPy arrays, for example, define `__eq__` to return an array of booleans rather than a single boolean. When such a result is used in a boolean context (`if result:`, `not result`, `result and ...`), Python cannot reduce it to a single truth value and raises an exception.

This is an **implicit assumption violation**: the code implicitly assumes that comparison operators always produce scalar booleans, but the type contract of the values flowing through the code path does not guarantee this. The mismatch between the assumed capability (scalar boolean comparison) and the actual capability (element-wise comparison) constitutes a **capability mismatch** at the type-coercion boundary.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ValueError: The truth value of an array is ambiguous. Use a.any() or a.all()`
  - `TypeError` when a non-scalar comparison result is used in a boolean context
  - Crashes occurring in serialization, repr generation, or parameter change-detection code paths
  - Failures triggered only when array-like objects (NumPy arrays, pandas DataFrames, etc.) are passed as parameter values

### 解决步骤
1. **Audit comparison sites**: Identify all code paths where values of unknown or heterogeneous types are compared using `==` or `!=` and the result is consumed as a scalar boolean (in `if`, `while`, ternary, or boolean operators).
2. **Assess value space**: Determine whether any of those values could be array-like types with overloaded comparison operators that return non-scalar results. Check parameter types, function signatures, and upstream callers.
3. **Replace with safe comparison**: Substitute direct value comparison with a strategy that always yields a scalar boolean:
   - **String representation comparison** (`repr(a) != repr(b)`): simplest and safest for display or change-detection purposes.
   - **Safe comparison utility**: wrap the check in a `try/except` that catches `ValueError` (ambiguous truth value), falling back to string comparison or `np.array_equal`.
   - **Explicit type dispatch**: check `isinstance` for known array-like types and use appropriate comparison (e.g., `np.array_equal`) before falling back to `==`.
4. **Prefer repr comparison for non-numerical contexts**: If the comparison is only for display, logging, or detecting whether a value has changed from its default (not for numerical correctness), `repr()` string comparison is the simplest and most robust approach.
5. **Add regression tests**: Include test cases that pass array-like parameter values (e.g., NumPy arrays, nested lists) through the affected code paths to ensure no future regressions.

### Why This Works

Comparing `repr()` strings always yields a scalar boolean because `str.__ne__` is guaranteed to return `True` or `False`. This sidesteps the entire class of element-wise comparison issues. For change-detection and display purposes, this is semantically adequate: identical objects produce identical string representations, so the comparison correctly identifies when a value differs from its default. The trade-off — that theoretically distinct objects could share a repr — is negligible in practice and vastly preferable to crashing. For contexts requiring numerical correctness, explicit type dispatch or utilities like `np.array_equal` provide element-wise accuracy while still producing a scalar boolean result.

## Boundary Cases
- **Objects with identical `repr()` but different values**: Rare in practice, but possible (e.g., truncated array representations). If numerical precision matters, use `np.array_equal` or a deep comparison utility instead of repr.
- **Custom objects with broken `__repr__`**: If `repr()` itself raises an exception, the safe comparison utility should catch this and fall back to identity comparison (`a is b`).
- **Nested structures containing arrays**: A dict or list containing NumPy arrays will also fail scalar comparison. The same pattern applies recursively; repr comparison handles this naturally.
- **Sparse matrices and other non-standard array-likes**: Types like `scipy.sparse` matrices may have different failure modes on `==` (e.g., returning sparse matrices). The solution must account for the full breadth of array-like types in the ecosystem.
- **NaN and None comparisons**: `repr()` comparison correctly distinguishes `NaN` values and `None`, but developers should be aware that `float('nan') != float('nan')` is `True` while `repr(float('nan')) != repr(float('nan'))` is `False` — a semantic difference that may matter in some contexts.

## PR Examples
- scikit-learn__scikit-learn-13584