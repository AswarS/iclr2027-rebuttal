## Problem Description

When a composite identity (such as a tuple used for hashing and equality comparison) is constructed from multiple object attributes, a normalization function may be applied to convert mutable containers (lists, sets, dicts) into their hashable equivalents (tuples, frozensets, etc.). The problem arises when this normalization is applied **selectively** — only to the most obviously mutable components — while other components that can also accept mutable input types through user-facing APIs are left unnormalized. This creates a latent `TypeError` (unhashable type) that surfaces only when a mutable variant happens to be passed for the overlooked component, often making the bug appear intermittent or path-dependent.

## Root Cause Analysis

The Python hash contract requires that every element within a tuple used as a dictionary key or set member must itself be hashable. When constructing composite identity tuples from object attributes, developers often recognize the need to normalize obviously mutable fields (e.g., converting a `dict` to a `frozenset` of items). However, they fall into a **selective normalization bias**: having addressed the most salient mutable type, they mentally categorize the problem as solved and fail to apply the same scrutiny to other fields in the identity tuple.

The underlying principle is one of **symmetry**: if the identity contract treats all components uniformly (they all participate in hashing and equality), then the normalization contract must also be uniform. Any component whose API contract permits mutable input — even if immutable input is more common in practice — is a potential source of hash failure. The root cause is the mismatch between the uniform requirements of the hash contract and the non-uniform application of normalization logic.

## Solution Strategy

### 识别信号
- 观测到的现象: `TypeError: unhashable type: 'list'` (or `'set'`, `'dict'`) raised during hash or dictionary/set operations on composite identity tuples.
- The crash may appear intermittent, surfacing only in specific code paths that trigger more hash operations or when users happen to pass mutable variants for a particular field.
- Stack traces point to `__hash__`, `__eq__`, or internal dictionary/set lookup operations on identity tuples.

### 解决步骤
1. **Identify the composite identity tuple**: Locate where the identity (used for `__hash__`, `__eq__`, caching keys, or deduplication) is constructed as a tuple from multiple object attributes.
2. **Audit every component for potential mutability**: For each attribute included in the identity tuple, examine the user-facing API contract. Determine whether lists, sets, dicts, or other mutable types are accepted as valid input — not just what is *typical*, but what is *possible*.
3. **Apply normalization uniformly**: Ensure the same hashability normalization utility (e.g., recursive conversion of lists→tuples, sets→frozensets, dicts→frozensets of items) is applied to **every** component that could possibly receive mutable input, not just the most obvious ones.
4. **Add regression tests with mutable variants**: For each component of the identity tuple, write test cases that pass mutable input types (e.g., a `list` where a `tuple` is typical, a `set` where a `frozenset` is expected) and verify that hashing, equality, and any dependent operations (caching, deduplication) succeed without error.

### Why This Works

The hash contract is absolute: all elements of a hashable composite must themselves be hashable. There is no room for "usually hashable" — a single mutable element in a single code path causes failure. By applying normalization uniformly to every component that *could* be mutable (rather than only those that are *obviously* mutable), the solution ensures the hash contract is satisfied regardless of input form. This mirrors the symmetry inherent in the identity contract itself: if all components participate equally in identity, they must all be equally safe to hash.

## Boundary Cases
- **Nested mutability**: A component may be a tuple (hashable) that contains a list (unhashable) nested within it. Normalization must be recursive, not just surface-level.
- **User-defined types**: Components may include user-defined objects that are mutable but happen to implement `__hash__`. These satisfy the hash contract but may violate equality consistency — a related but distinct concern.
- **Empty mutable containers**: An empty `list` or `dict` is still unhashable. Normalization must not skip empty containers.
- **Components that are "always" immutable in practice**: If the API technically permits mutable input but no current caller provides it, the bug is latent. Defensive normalization protects against future callers.
- **Performance-sensitive paths**: If normalization is expensive and the identity is computed frequently, consider normalizing at construction time (once) rather than at each hash call.

## PR Examples
- django__django-14672