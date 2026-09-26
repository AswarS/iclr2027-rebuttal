## Problem Description

When a lookup operator with strict boolean semantics (e.g., a null-check / `isnull` lookup) accepts arbitrary truthy/falsey values instead of enforcing an actual `bool` type, downstream logic that inspects the raw value — rather than its truthiness — silently produces structurally incorrect results. The problem is insidious because simple cases appear to work fine; the incorrectness only surfaces in complex scenarios such as multi-table joins, query optimization passes, or null-handling logic that branches on the exact value rather than its boolean interpretation.

This is a general instance of **truthiness-vs-type-contract violation**: an API parameter has a strict type contract (boolean), but the implementation never enforces it, allowing non-boolean values to flow through and corrupt decisions made by code that reasonably assumes the contract holds.

## Root Cause Analysis

The root cause is a mismatch between the **semantic contract** of a parameter and the **enforcement** of that contract at the boundary where the value enters the system.

1. **Implicit assumption**: Downstream query-generation code assumes the lookup value is literally `True` or `False` and uses identity or equality checks against these values to decide join types, null-handling branches, and query structure.
2. **Missing validation**: The entry point that accepts the value never verifies `isinstance(value, bool)`, so integers (`0`, `1`), strings (`""`, `"true"`), `None`, and other types pass through unchallenged.
3. **Truthiness ≠ Type identity**: In Python, `1 == True` and `0 == False` evaluate to `True`, but `isinstance(1, bool)` is `False`. Code that checks `if value:` behaves differently from code that checks `if value is True:` or `if value == True:` when the value is a non-boolean truthy/falsey object. This divergence causes silent structural errors.
4. **Masking in simple cases**: For trivial queries (single table, no joins), the wrong internal structure still produces correct SQL by coincidence, so the bug remains hidden until query complexity increases.

The underlying principle: **when downstream logic depends on type identity rather than truthiness, the boundary must enforce type identity — otherwise the system silently degrades.**

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss / wrong output**: Queries return incorrect results (e.g., missing rows, wrong join types) when non-boolean values are passed to a boolean-contract lookup.
  - **Missing validation**: No `TypeError` or `ValueError` is raised for clearly invalid inputs like `isnull=1`, `isnull="yes"`, or `isnull=None`.
  - **Structural query incorrectness**: Generated SQL uses inner joins where outer joins are required (or vice versa), or omits null-handling clauses, but only in multi-join or optimized query scenarios.
  - **Implicit assumption violation**: Downstream code uses `value is True` / `value is False` or branches on the raw value, assuming it is a bool.

### 解决步骤
1. **Locate the consumption point**: Find where the lookup's right-hand side value is first consumed for query generation — the method that processes the value before it influences join promotion, null handling, or SQL construction.
2. **Add an explicit type check**: Insert `if not isinstance(value, bool):` immediately at this consumption point, before any downstream logic inspects the value.
3. **Raise a hard error**: Raise `ValueError` with a clear message: state that the lookup requires a boolean value and report the actual type received. Do **not** coerce to `bool` and do **not** use a deprecation warning — the non-boolean path was never intentionally supported and already produces incorrect results.
4. **Preserve normal flow**: After the guard clause, leave all existing boolean-handling logic untouched. `True` and `False` continue through the original code path.
5. **Add comprehensive tests**:
   - `ValueError` is raised for representative non-boolean types: `int` (`0`, `1`), `str` (`""`, `"true"`), `None`, `float`, collections.
   - `True` and `False` continue to produce correct results.
   - Complex query scenarios (joins, subqueries, aggregations) produce the correct SQL structure when proper boolean values are used.

### Why This Works

By enforcing the type contract at the boundary, we eliminate the entire class of bugs where non-boolean values flow into code that assumes boolean identity. A hard error is appropriate because:

- The non-boolean usage was **never part of the intended API** — it was accidental permissiveness.
- Any existing code passing non-boolean values is **already producing subtly incorrect results** in complex queries, so failing loudly is strictly better than silent corruption.
- A minimal `isinstance` check is the smallest possible change that closes the gap between the semantic contract and its enforcement, avoiding the complexity of deprecation machinery or coercion logic.

## Boundary Cases

- **`0` and `1`**: These are the most dangerous inputs because `bool` is a subclass of `int` in Python, so `1 == True` is `True` — but `isinstance(1, bool)` is `False`. Code must check `isinstance(value, bool)` rather than `value in (True, False)` or `value == True`.
- **`None`**: Often used to mean "unset" or "missing," but passing `None` to a null-check lookup is semantically nonsensical and must be rejected.
- **Numpy/third-party boolean types**: `numpy.bool_` and similar types are not `isinstance(..., bool)`. If the system needs to support these, the check should be extended — but the default should be strict, with explicit opt-in for known compatible types.
- **Strings like `"true"`, `"false"`, `"0"`, `"1"`**: Always truthy (non-empty strings), so they would silently produce the "is not null" query branch regardless of intent. Must be rejected.
- **Subclasses of `bool`**: `bool` cannot be subclassed in CPython, so `isinstance(value, bool)` is a complete check for standard Python booleans.
- **Values arriving through deserialization**: Form data, JSON payloads, or URL parameters often arrive as strings. The validation error provides a clear signal to the caller that explicit conversion to `bool` is required before passing the value to the lookup.

## PR Examples

- **django__django-11905**: `isnull` lookup accepted non-boolean values, causing incorrect join type promotion and null handling in generated SQL. Fixed by adding an `isinstance(value, bool)` check that raises `ValueError` for non-boolean inputs.