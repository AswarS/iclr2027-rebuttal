## Problem Description

In multi-step data transformation pipelines that process key-value structures (dictionaries, maps, etc.), a common and subtle bug arises when a cleanup/filtering step removes entries with sentinel or absent values (e.g., `None`) **before** a downstream branching step that relies on the **existence of keys** — not their values — to choose between fundamentally different processing paths. The filtering collapses two independent pieces of information (structural metadata: "a named slot exists" vs. value metadata: "what was captured in that slot") into one, making "named slot that captured nothing" indistinguishable from "no named slots at all." This leads to incorrect dispatch, wrong argument passing conventions, or outright crashes when optional/nullable named parameters legitimately resolve to `None`.

## Root Cause Analysis

The underlying principle is that **key existence** and **key value** are orthogonal semantic signals in a dictionary, but developers performing cleanup naturally conflate **"has no useful value"** with **"never existed."** When a filtering step strips out `None`-valued entries as a simplification, it inadvertently destroys structural metadata that downstream logic depends on. The root cause is an **ordering dependency violation**: data reduction steps are placed before all consumers of the pre-reduction shape of the data.

More concretely:

- A pattern-matching or parsing layer produces a dictionary where keys represent named capture groups and values represent what was captured. An optional group that matches but captures nothing yields `{key: None}`, while the absence of any named groups yields `{}`.
- A branching decision downstream checks `if kwargs:` (structural query on key existence) to decide between keyword-argument dispatch and positional-argument dispatch.
- A well-intentioned cleanup step like `{k: v for k, v in kwargs.items() if v is not None}` placed **before** this branch makes both cases look identical (`{}`), triggering the wrong dispatch path.

The general principle: **structural metadata (what keys exist) and value metadata (what those keys hold) have independent lifetimes and must not be destroyed together.** Data reduction must be ordered after all consumers that depend on the pre-reduction shape.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A refactor or version upgrade introduces a **regression** where optional/nullable named parameters suddenly cause unexpected positional argument errors or wrong dispatch paths
  - `TypeError` or similar **crash exceptions** when calling functions with positional arguments that should have been dispatched as keyword arguments
  - The bug only manifests on **edge cases** where a named capture group is present in the pattern but matches the empty/None case — normal non-None captures work fine

### 解决步骤
1. **Map the pipeline**: Enumerate every step that reads or transforms the dictionary between its creation (e.g., regex match, URL resolution) and its final consumption (e.g., view function call).
2. **Classify each consumer**: For each step, determine whether it performs a **structural query** (depends on which keys exist, e.g., `if kwargs:`, `len(kwargs)`, `'name' in kwargs`) or a **value query** (depends on what values the keys hold, e.g., passing values to a function).
3. **Locate the filtering step**: Find where `None`-valued entries are removed (e.g., dictionary comprehension filtering out `None`, `dict.pop()` calls, or similar cleanup).
4. **Reorder**: Move the `None`-value filtering to occur **after** all structural query steps — specifically after the branching decision that checks whether named keys exist in the result dictionary. The filtering should happen immediately before (or as part of) the value-consuming step.
5. **Add regression tests**: Create a test case with an optional named capture group that legitimately resolves to `None`, verifying that:
   - The correct dispatch path (keyword vs. positional) is chosen
   - The function receives the expected arguments
   - Both the `None`-match and non-match cases behave correctly

### Why This Works

By deferring the removal of `None`-valued keys until after all structural queries have been evaluated, we preserve the two independent signals: (a) "a named slot exists in the pattern" and (b) "the runtime value captured for that slot." The branching logic can correctly distinguish between "named parameters present but optional group captured nothing" and "no named parameters at all." The cleanup still happens — just at the right point in the pipeline where it no longer destroys information that other steps need.

## Boundary Cases
- **All named groups capture `None`**: The dictionary is non-empty (structural signal preserved) but every value is `None`. After reordering, the branch correctly chooses keyword dispatch; the subsequent filtering may yield an empty dict, but the dispatch decision is already made.
- **Mix of `None` and non-`None` values**: Filtering before branching might not cause a bug here (dict is still non-empty), but the pattern is still fragile — it breaks the moment the last non-`None` value becomes `None`.
- **Empty pattern with no named groups**: The dictionary is `{}` from the start. No filtering occurs, and the positional dispatch path is correctly chosen. This case is unaffected by the reordering.
- **Nested or chained pipelines**: If the dictionary passes through multiple intermediate layers (middleware, decorators, resolver chains), each layer must be audited to ensure none performs premature key removal.
- **Sentinel values other than `None`**: The same pattern applies to any sentinel (empty string, `0`, `False`) if filtering removes entries based on falsiness rather than explicit `None` checks.

## PR Examples
- **django__django-12184**: URL resolver filtered `None`-valued kwargs from optional regex capture groups before the dispatch logic that checked `if kwargs:` to decide between keyword and positional argument passing to views, causing a regression where optional URL parameters triggered incorrect positional dispatch.