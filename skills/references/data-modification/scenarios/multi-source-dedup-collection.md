## Problem Description

When multiple independent sources (e.g., user-provided configuration and automatic discovery mechanisms) contribute items to a shared collection used for duplicate detection, false-positive duplicate errors can arise if the collection data structure permits redundant insertions of the same logical entry. The core issue is that a count-based duplicate check on a list conflates "the same item registered from N different code paths" with "N genuinely distinct items sharing the same key." Users encounter spurious conflict/duplicate error messages for entries that are perfectly valid and identical, simply because they were registered more than once through overlapping sources.

## Root Cause Analysis

The underlying principle is an **implicit assumption of source disjointness**. The original code assumes that each registration source contributes a unique, non-overlapping set of entries to the shared collection. When this assumption is violated — for example, when a user explicitly configures an item that is also found by an automatic discovery/scanning mechanism — a list-based accumulator faithfully records every insertion, inflating the count. A subsequent validation check (e.g., `len(entries) > 1`) then incorrectly interprets the inflated count as evidence of genuinely conflicting entries, producing a false-positive error. This is a **symmetry-breaking** problem: two code paths that should be treated as equivalent contributors are instead treated as independent witnesses of a conflict.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Incorrect error messages**: Users receive duplicate/conflict warnings or errors for entries that are not actually duplicated — the "conflicting" values are identical.
  - **Wrong output**: Diagnostic or validation output lists the same value multiple times as if it were distinct entries.
  - The problem surfaces specifically when an item is both explicitly configured and automatically discovered (or registered by two overlapping pipelines).

### 解决步骤
1. **Locate the accumulation data structure**: Find where entries are aggregated per key during the collection/validation phase. Typically this is a dictionary mapping keys to lists (e.g., `defaultdict(list)` with `.append()` calls).
2. **Replace list-based accumulation with set-based accumulation**: Change the per-key container from a `list` to a `set` (e.g., `defaultdict(set)` with `.add()` calls). This ensures that identical values contributed by multiple sources are automatically deduplicated at insertion time, with no need for conditional deduplication logic.
3. **Apply deterministic ordering to output**: When the set contents are used in error messages, logging, or test assertions, wrap the iteration with `sorted()` or another deterministic ordering mechanism. Sets have no guaranteed iteration order, so this prevents introducing non-deterministic behavior.
4. **Verify the duplicate-check threshold**: Confirm that the existing check (e.g., `len(entries) > 1`) now correctly reflects truly distinct entries rather than raw insertion count. No threshold change should be needed if the set is correctly substituted, but verify edge cases.

### Why This Works

A set enforces value uniqueness at insertion time, which is the simplest and most idiomatic way to distinguish "the same item seen from multiple paths" from "genuinely different items sharing a key." The cognitive trap is assuming source disjointness — that each registration path contributes entries the other does not. By using a set, the code becomes **agnostic to how many times or from how many sources** an identical entry is registered; only genuinely distinct values survive accumulation. The count-based check then operates on the correct semantic quantity. Sorting the output is a necessary companion change to preserve deterministic, reproducible behavior in user-facing messages and test suites.

## Boundary Cases
- **All sources contribute the exact same entry**: After deduplication, the set has size 1 and no error should be raised — this is the primary false-positive case being fixed.
- **Sources contribute genuinely different entries for the same key**: The set correctly retains all distinct values, and the duplicate check fires as intended — no regression.
- **Entry equality semantics**: If entries are mutable or unhashable objects, a direct switch to `set` will fail. Ensure the accumulated values are hashable (strings, tuples, etc.) or define appropriate `__hash__`/`__eq__` methods.
- **Order-dependent downstream consumers**: Any code that previously relied on list insertion order for the accumulated entries must be audited. The `sorted()` wrapper addresses output formatting, but other consumers may need attention.
- **Single-source scenarios**: When only one source contributes entries, the behavior is unchanged — lists and sets behave identically for unique insertions.

## PR Examples
- django__django-15790