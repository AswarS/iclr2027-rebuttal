## Problem Description

When a discrete lookup table (mapping keys to visual or computed values) is constructed from a user-specified subset of all possible keys — such as an explicit ordering, filter list, or palette that intentionally excludes some values present in the data — the fallback path for missing keys incorrectly assumes that any absent key must belong to a continuous (numeric) domain. This causes the system to attempt numeric interpolation or coercion on non-numeric categorical values, resulting in type errors and crashes. The core issue is a **false dichotomy in the key-resolution logic**: the code assumes every key is either (a) present in the discrete table or (b) a continuous value requiring interpolation, without accounting for the third possibility that the key was intentionally excluded by the user's subset configuration.

## Root Cause Analysis

The underlying principle is an **exhaustive dichotomy assumption** — the original developer modeled the lookup as having exactly two states: "key found in discrete map" and "key not found, therefore continuous." This two-branch logic is correct only when the discrete table's domain is guaranteed to cover all keys that will ever be queried. The moment the table's domain becomes user-configurable (e.g., via explicit palette dictionaries, ordering lists, or filter parameters), a third category emerges: keys that are legitimately present in the data but intentionally excluded from the mapping.

Because the system does not filter data upstream to match the user-specified subset, all data points — including those with excluded keys — flow through to the lookup. When an excluded categorical key hits the "not found" branch, it falls through to numeric interpolation logic, which attempts operations like normalization or float conversion on a string or other non-numeric type, producing a `TypeError` or similar crash.

This is a specific instance of the broader **implicit assumption violation** pattern: a boundary-handling path was written under assumptions about the input domain that no longer hold once the system's configuration surface expands.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `ValueError` when categorical/string values are passed to numeric interpolation or normalization functions
  - Crash occurs only when a user-specified palette, order, or filter excludes some categories that still exist in the data
  - Regression on edge cases: the code works fine when all categories are included, but breaks when a subset is specified
  - The traceback typically shows a non-numeric value entering a code path designed for continuous float operations

### 解决步骤
1. **Locate the key-resolution logic** in the lookup/mapping layer. Identify the point where a missing key triggers a fallback — typically a `try/except KeyError`, an `if key not in table` branch, or a dictionary `.get()` call whose default leads to interpolation.

2. **Add a guard that checks whether a continuous normalization scheme is actually configured** before entering the numeric interpolation path. This is the critical missing condition: the fallback should only attempt interpolation when the mapping was explicitly set up for continuous data (e.g., a `Normalize` object, a numeric scale, or a colormap with a defined numeric domain).

3. **Introduce a third branch for intentional exclusion.** When the key is not found in the discrete table *and* no continuous scheme is configured, return a neutral/invisible sentinel value — such as a fully transparent color (e.g., `(0, 0, 0, 0)`), `NaN`, `None`, or a designated "skip" marker — that downstream rendering will silently omit or ignore.

4. **Verify that downstream consumers handle the sentinel gracefully.** Ensure that plotting, aggregation, or transformation code that receives the sentinel value does not crash — e.g., matplotlib will simply not render fully transparent artists, and NaN values are typically excluded from statistical computations.

5. **Ensure the final fallback structure has three explicit branches:**
   - (a) Key found in discrete table → return the mapped value directly.
   - (b) Key not found, but continuous normalization is configured → interpolate/normalize the key as a numeric value.
   - (c) Key not found, no continuous scheme → return the sentinel for graceful exclusion.

### Why This Works

The solution correctly models the three-state reality of key resolution when the lookup domain is user-configurable. By checking for the presence of a continuous normalization scheme before attempting interpolation, the code no longer conflates "intentionally excluded discrete key" with "continuous domain member." The sentinel value approach is minimally invasive — it preserves the existing data flow without requiring upstream filtering or data mutation, and it matches the intuitive user expectation that excluded values simply don't appear in the output. This pattern generalizes: **any time a lookup table's domain is user-configurable, the error/fallback handler must distinguish "key excluded by design" from "key belongs to a different mapping paradigm."**

## Boundary Cases

- **All categories excluded except one:** The lookup table contains a single entry; all other data points should receive the sentinel. Verify that the output still renders the one included category correctly.
- **Empty subset / empty palette:** The user specifies an empty ordering or palette. Every key is "excluded." The system should either raise a clear configuration error or produce an empty (but non-crashing) output.
- **Mixed numeric and categorical keys:** If the data contains both numeric and string values and the user subset excludes some of each, the guard must correctly route numeric missing keys to interpolation (if continuous scheme exists) while returning sentinels for string missing keys.
- **Sentinel value propagation:** Downstream aggregation (e.g., mean, count) or legend generation must not break when encountering sentinel/NaN values. Legends should only show categories that are in the user-specified subset.
- **User expects an error, not silent exclusion:** In some contexts, a missing key might indicate a user typo rather than intentional exclusion. Consider whether a warning (not an exception) should be emitted when keys are silently excluded, to aid debugging.
- **Duplicate or overlapping subsets:** The user-specified subset contains keys not present in the data at all. This is the inverse case — the lookup table has entries that are never queried. This should not cause errors but may affect legend or axis tick generation.

## PR Examples

- **mwaskom__seaborn-2848**: A seaborn color mapping lookup crashed with a `TypeError` when a user-specified palette excluded some categorical values present in the data. The missing keys fell through to a numeric interpolation path that attempted float conversion on strings. The fix introduced a check for whether continuous normalization was configured before interpolating, and returned a transparent color sentinel for intentionally excluded categories.