## Problem Description

When generic sequence comparison or diff formatting code extracts individual elements from containers using index notation, certain Python types exhibit a **representation asymmetry**: the type returned by indexing differs from what the container's own `repr` visually suggests. The canonical example is `bytes` in Python 3, where `b'hello'[0]` returns `104` (an `int`), not `b'h'` (a `bytes` object). This causes diff output, error messages, and assertion introspection to display confusing, type-inconsistent representations — e.g., showing `52` where the user expects `b'4'`.

This pattern generalizes to any container type where `type(container[i])` is not the same as `type(container[i:i+1])`, and where the slice form preserves the visual representation contract that users expect.

## Root Cause Analysis

The underlying issue is an **implicit assumption of uniform repr consistency across access patterns**. Most common Python sequence types (lists, tuples, strings) satisfy the invariant that `repr(container[i])` visually corresponds to the element as it appears inside `repr(container)`. Generic formatting code is naturally written against this assumption.

However, `bytes` and `bytearray` in Python 3 break this invariant: indexing performs an implicit type coercion from the container's element domain (byte values displayed as character-like literals) to a raw integer. The formatter, unaware of this coercion, calls `repr()` on the integer result and produces output that is visually alien to the user's mental model of the data.

The cognitive trap is subtle because:
- The code works correctly for the vast majority of sequence types.
- The coercion is silent — no error is raised, just a different type is returned.
- The mismatch only becomes visible in the *formatted output*, not in the program's logical behavior.

## Solution Strategy

### 识别信号
- 观测到的现象: Error messages or diff output display raw integers (e.g., `52`, `104`) where users expect byte literals (e.g., `b'4'`, `b'h'`), or similar type-representation mismatches in assertion introspection or comparison formatters.
- Diff lines show elements whose `repr` style is inconsistent with the container's own `repr` style.
- Users report "wrong output" or "incorrect error message" in assertion failure reports involving `bytes`, `bytearray`, or other specialized sequence types.

### 解决步骤
1. **Audit all element extraction points** in the generic formatter: find every place where `container[i]` is used to extract a single element for display purposes. Catalog which sequence types are handled.
2. **Replace index access with slice access** for types where indexing causes type coercion. Use `container[i:i+1]` instead of `container[i]` for `bytes`, `bytearray`, and any other identified types. Slicing preserves the container type, so `repr(container[i:i+1])` matches the visual style of `repr(container)`.
3. **Adapt or suppress summary messages** (e.g., "first extra item: ...") that would also display the coerced type. If the full diff already conveys the information clearly, omit the summary line for these special types to avoid confusion.
4. **Add targeted test cases** that compare sequences of different lengths and content for each affected type, asserting that the formatted diff output contains type-consistent literals (e.g., `b'4'` not `52`).

### Why This Works

Slicing a sequence always returns an object of the same type as the original container. For `bytes`, `s[i:i+1]` returns a `bytes` object of length 1, whose `repr` (e.g., `b'4'`) is visually consistent with how that byte appears inside the full container's `repr`. This restores the invariant that the generic formatter implicitly depends on: **the displayed element looks like it belongs to the displayed container**.

The broader principle is: when writing generic code that formats or displays elements extracted from heterogeneous container types, always verify that the extraction method preserves the type and representation semantics expected by the end user. Prefer slice-based extraction when representation fidelity matters more than the raw value.

## Boundary Cases
- **Empty sequences**: Ensure slice-based extraction handles edge cases where `i:i+1` is at or beyond the sequence boundary without raising errors.
- **`bytearray` vs `bytes`**: Both exhibit the same indexing coercion; ensure both are covered by the fix.
- **Custom sequence types**: Third-party or user-defined sequences may also have indexing-coercion behavior (e.g., NumPy arrays where `arr[0]` returns a scalar type). The fix should be extensible or at minimum not regress for standard types.
- **Single-element sequences**: `b'\x00'[0]` → `0` is particularly confusing; verify the fix handles non-printable bytes correctly.
- **Mixed-type comparisons**: Comparing `bytes` against `list` or other types should not trigger the slice-based path inappropriately.

## PR Examples
- `pytest-dev__pytest-5495`: Fixed assertion rewriting for `bytes` comparisons where diff output showed integers instead of byte literals due to index-based element extraction in the sequence comparison formatter.