## Problem Description

When a function parameter is polymorphic — accepting multiple types such as a string sentinel (e.g., `'auto'`), a boolean, or an array-like collection — using direct value comparison (`param == 'sentinel'`) to dispatch behavior is unsafe. Array-like types (e.g., NumPy arrays) overload the `==` operator to perform element-wise comparison, which means `array == 'auto'` does not return a simple `False` but instead produces a boolean array, a `FutureWarning`, or raises an error depending on the library version. This breaks the intended dispatch logic and leads to subtle, hard-to-diagnose failures.

## Root Cause Analysis

The underlying principle is that **equality comparison is not a type-safe dispatch mechanism**. Developers implicitly assume that `x == 'auto'` will simply return `False` when `x` is not a string. This assumption holds for most scalar types (int, float, bool) but breaks catastrophically for types that overload comparison operators, such as NumPy arrays, pandas Series, or other collection types. The `==` operator is invoked *before* the type of the operand is known, and the overloaded behavior produces a result that is neither `True` nor `False` — it is a collection of booleans, which cannot be used in a conditional branch and triggers warnings or errors.

This is a specific instance of the broader **implicit-assumption-violation** pattern: code assumes a universal behavior of a language operator that is actually polymorphic and context-dependent. The fix requires making the type check explicit and placing it *before* any value comparison.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `FutureWarning` or `DeprecationWarning` from NumPy about element-wise comparison of unlike types
  - `ValueError: The truth value of an array is ambiguous` when the result of `==` is used in an `if` statement
  - Silent incorrect behavior where an array parameter is misinterpreted or falls through to the wrong code path
  - Type errors or unexpected coercion when a collection is passed to a parameter that also accepts string sentinels

### 解决步骤
1. **Audit all polymorphic parameters** in the function signature. Identify every parameter that accepts both scalar sentinels (strings like `'auto'`, `'warn'`, booleans) and collection types (arrays, lists, boolean masks).
2. **Replace value-based dispatch with type-based dispatch.** Before comparing the parameter's value against a sentinel string, first check `isinstance(param, str)`. This ensures the `==` operator is never applied across incompatible types.
   ```python
   # Before (unsafe):
   if sample_weight == 'auto':
       ...

   # After (safe):
   if isinstance(sample_weight, str) and sample_weight == 'auto':
       ...
   ```
3. **Order `isinstance` checks from narrow to broad.** Check `str` and `bool` before `int` or general numeric types, since `bool` is a subtype of `int` in Python and ordering matters to avoid misclassification.
4. **Add explicit validation within each type branch.** If the parameter is a string but not the expected sentinel value, raise a `ValueError` immediately with a clear message rather than allowing it to fall through to array-handling logic.
5. **Use framework-standard input validation utilities** (e.g., `check_array`, `column_or_1d`) for the collection-type branch to catch malformed inputs early and provide clear error messages.

### Why This Works

By checking the type *before* comparing the value, the equality operator is only ever invoked between compatible types (e.g., `str == str`). This completely eliminates the possibility of triggering overloaded comparison behavior on array-like objects. The approach follows the principle of **fail-fast validation**: each type branch validates its own invariants immediately, preventing silent misinterpretation and ensuring that unrecognized inputs produce clear, actionable errors at the point of entry rather than deep in downstream logic.

## Boundary Cases
- **`bool` as a subtype of `int`:** If the parameter accepts both booleans and integers, check `isinstance(param, bool)` before `isinstance(param, int)`, since `isinstance(True, int)` returns `True` in Python.
- **NumPy scalar types:** A NumPy `np.str_` value may not pass `isinstance(x, str)` in all Python/NumPy version combinations. Consider using `isinstance(x, (str, np.str_))` if NumPy string scalars are valid inputs.
- **`None` as a sentinel:** If `None` is also a valid sentinel value, check for it with `param is None` before any type or value checks, since `None` comparisons with arrays also produce unexpected results.
- **Nested or chained comparisons:** Ensure that all code paths where the parameter is compared — not just the first branch — are protected by type checks. Grep for all usages of the parameter, not just the initial dispatch point.
- **Deprecation transitions:** When changing a parameter from accepting a string sentinel to a different type (e.g., replacing `'auto'` with `True`/`False`), the type-check-first pattern is essential during the deprecation period when both old and new value types must coexist.

## PR Examples
- scikit-learn__scikit-learn-13497