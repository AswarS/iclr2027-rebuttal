## Problem Description

When a function uses `next()` on a generator/iterator to find the first element satisfying a predicate (e.g., first finite value, first non-null entry), and the input collection contains **no** elements that satisfy the predicate, the iterator is exhausted and `next()` raises `StopIteration`. This exception is structurally different from the domain-specific exceptions (e.g., `TypeError`, `ValueError`) that callers typically catch, causing it to propagate uncaught and crash the program. The pattern commonly arises when a prior bug fix introduces a "find first valid element" search under the implicit assumption that at least one valid element exists, without accounting for fully-degenerate inputs (e.g., all-NaN data, entirely empty or filtered-out sequences).

## Root Cause Analysis

The root cause is **survivorship bias in edge-case reasoning** combined with **implicit assumption violation**. When a developer fixes a bug caused by a single bad element (e.g., the first value is NaN), they naturally reason about inputs where *some* elements are problematic and others are valid. The mental model treats bad values as occasional outliers. This leads to an implicit, untested assumption that the iterator search will always find at least one match. The `next()` built-in, when called without a default, raises `StopIteration` on exhaustion — an exception type that is almost never included in the `except` clauses of calling code, because it is not a domain-level error. The result is that a fix for a partial-degenerate case (some bad elements) introduces a regression on the fully-degenerate case (all bad elements).

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Unhandled `StopIteration` exception crashing the program on inputs where all elements fail a predicate (e.g., all-NaN arrays, all-null collections).
  - A regression introduced by a recent fix that added a `next()` call with a generator expression but no default value.
  - Exception traceback pointing to a `next(x for x in collection if predicate(x))` pattern.
  - The crash only manifests on fully-degenerate inputs, not on partially-degenerate ones.

### 解决步骤
1. **Locate the `next()` call on a generator/iterator** that searches for the first element satisfying a predicate. Confirm it lacks a default value argument.
2. **Determine the appropriate fallback** for the exhaustion case. Typically, falling back to the unconditional first element of the original collection (e.g., `next(gen, collection[0])`) restores pre-fix behavior for degenerate inputs. The non-conforming value will propagate naturally through downstream logic (e.g., NaN produces invisible graphical output rather than a crash).
3. **Decide where to handle exhaustion.** If the search function is shared across multiple call sites, prefer one of two strategies:
   - Supply a default to `next()` directly (e.g., `next(gen, fallback)`) if the fallback is universally appropriate.
   - Catch `StopIteration` explicitly at each call site if different callers need different fallback strategies — this preserves the function's clear "find or fail" contract.
4. **Add tests for the fully-degenerate case** (all elements fail the predicate) alongside the existing partially-degenerate case (only some elements fail). Ensure the code path no longer raises `StopIteration` and instead produces a graceful, well-defined result.
5. **Review other `next()` calls in the codebase** for the same pattern — iterator exhaustion neglect tends to recur wherever `next()` is used without a default.

### Why This Works

Providing a default value to `next()` (or explicitly catching `StopIteration`) eliminates the unhandled exception by converting iterator exhaustion from a crash into a controlled fallback. Falling back to the unconditional first element is safe because downstream processing already has its own handling for non-conforming values (e.g., NaN propagation, null checks). This approach preserves the original bug fix for the partial-degenerate case while restoring correct behavior for the fully-degenerate case, without altering the shared function's contract or introducing silent data corruption.

## Boundary Cases
- **All elements fail the predicate** (e.g., an entirely NaN array): the primary case this pattern addresses — `next()` exhausts the iterator and must fall back gracefully.
- **Empty collection**: the generator yields nothing and `next()` raises `StopIteration`; additionally, fallback to `collection[0]` would raise `IndexError` — this case may need a separate guard.
- **Single-element collection where that element fails the predicate**: a minimal reproducer that is easy to overlook in testing.
- **Nested generators or chained `next()` calls**: `StopIteration` can leak across generator boundaries in Python < 3.7 (PEP 479), causing even more confusing failures.
- **Mixed-type collections** where the predicate raises an exception on some elements rather than returning `False`: the generator may short-circuit with a different exception before exhaustion.

## PR Examples
- matplotlib__matplotlib-24149