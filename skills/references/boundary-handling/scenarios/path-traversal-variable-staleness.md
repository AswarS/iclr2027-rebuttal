## Problem Description

This scenario addresses a **path-traversal variable staleness** bug pattern that occurs in iterative resolution algorithms. When a multi-segment dotted path (e.g., `a__b__c_id`) is resolved step-by-step through a chain of relations, a variable holding the original full path string may be incorrectly compared against a locally-scoped field name at the terminal step. Because the variable was never narrowed to reflect the current resolution context, the comparison always fails for multi-segment paths, causing the system to misinterpret the terminal field — typically following a relation further than intended and inheriting unwanted side effects such as extra JOINs or incorrect ordering.

This is a specific instance of the broader **partial-propagation** / **implicit-assumption-violation** pattern: an iterative algorithm updates some state variables as it traverses each segment but neglects to update (or scope) a companion variable that is consumed in a final guard condition.

## Root Cause Analysis

The core issue is a **namespace mismatch between the original input and the resolved context**. In an iterative path-resolution loop:

1. The path `a__b__c_id` is split into segments `[a, b, c_id]`.
2. Each segment is resolved in turn, advancing through model relations.
3. At the terminal step, a guard condition checks whether the resolved field's local attribute name (e.g., `c_id`) matches a "name" variable to decide if the field should be treated as a concrete column or if the relation should be followed further.
4. **The bug**: the "name" variable still holds the full original path string (`a__b__c_id`) rather than the terminal segment (`c_id`). Since `c_id != a__b__c_id`, the guard always fails for multi-segment paths.

This causes the algorithm to incorrectly follow the relation one step further, which introduces an unnecessary JOIN and may inherit the related model's default ordering — producing wrong query output. The problem is especially visible when the terminal relation is **self-referencing**, because the extra follow-through loops back to the same model with potentially different ordering semantics.

The cognitive trap is assuming that a variable initialized from user input remains semantically valid after multiple levels of iterative narrowing. Each traversal step narrows the resolution context, but the stale variable doesn't narrow with it.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: Generated queries contain unexpected extra JOINs.
  - **Regression on edge cases**: Sort direction or sort column is incorrect, inheriting a descending default ordering from a related model.
  - Single-segment paths work correctly; the bug only manifests with two or more segments.
  - Self-referencing foreign keys amplify the symptom because the extra relation-follow loops back to the same table with different ordering.

### 解决步骤
1. **Locate the traversal loop**: Find where the dotted path is split into segments and resolved iteratively through model relations, advancing the "current model" and "current field" at each step.
2. **Inspect the terminal guard condition**: Identify the post-loop comparison that checks the resolved field's local attribute name (e.g., `field.attname`) against a "name" variable to decide whether to treat the field as a direct column reference.
3. **Verify what "name" holds**: Confirm that at the point of comparison, the variable still contains the full original dotted path rather than just the terminal segment. This is the stale variable.
4. **Fix the comparison**: Replace the stale full-path variable with the last segment of the already-split path (e.g., `pieces[-1]` or the equivalent loop-local variable). The terminal field's attribute name corresponds only to the final segment.
5. **Add regression tests**:
   - (a) Multi-segment path ending in an `_id` suffix on a self-referencing foreign key.
   - (b) Single-segment path (confirm no regression).
   - (c) Multi-segment path on a non-self-referencing foreign key.

### Why This Works

The resolved field's local attribute name (e.g., `root_id`) is a property of the final model in the chain and can only match the **last segment** of the lookup path. Comparing it against the full dotted path is a category error — the namespaces are fundamentally different. Using the final path segment restores the correct semantic equivalence between the comparison operands, ensuring the guard condition fires when the terminal field is indeed a concrete column rather than a relation to follow.

## Boundary Cases
- **Single-segment paths**: The full path and the terminal segment are identical, so the bug is invisible — the comparison accidentally succeeds. Tests must cover this to ensure the fix doesn't regress.
- **Self-referencing foreign keys**: The extra relation-follow loops back to the same model, making the symptom (wrong ordering, extra JOIN) particularly confusing to diagnose.
- **Non-self-referencing multi-segment paths**: The bug still causes an incorrect extra JOIN, but the symptom may be subtler if the related model has no default ordering.
- **Paths where the terminal segment happens to equal the full path by coincidence**: Extremely unlikely in practice but worth noting as a degenerate case where the bug would be masked.
- **`_id` suffix fields**: These are the most common trigger because they reference the concrete column of a foreign key, and the guard condition specifically distinguishes "use the column directly" from "follow the relation."

## PR Examples
- django__django-13033