## Problem Description

When a recursive function processes nested collections by recursing into sub-elements and then aggregating results (e.g., using `zip(*results)`, unpacking, or destructuring), the empty collection case is frequently overlooked. The function typically handles two cases — a base case for scalar/leaf elements and a recursive case for non-empty collections — but fails catastrophically when given an empty collection. Operations like `zip(*[])` or `a, b = zip(*[])` are undefined on zero elements, leading to `ValueError` (unpacking) or `IndexError` (empty iterable access). The empty collection is a valid, meaningful input (e.g., a zero-length dimension, an empty container) that represents a distinct third case requiring explicit handling.

## Root Cause Analysis

Recursive functions over collections naturally have **three** distinct cases: (1) the leaf/scalar element (non-iterable base case), (2) the non-empty collection (recurse into children and aggregate), and (3) the empty collection. Developers almost universally implement only the first two because they mentally trace execution with non-empty examples during development and testing. The empty collection is neither an atom nor a collection-with-children — it occupies a blind spot between the two implemented cases.

The deeper cognitive trap is the **implicit non-emptiness assumption**: when the recursive case handles "collections" and the base case handles "atoms," it *feels* like all inputs are covered. But the aggregation step (e.g., `zip(*results)` where `results` is an empty list) silently encodes a non-emptiness precondition without an explicit check. Transposing a zero-row matrix is mathematically undefined, and most languages reflect this by raising an exception. The empty collection must be handled **before** the aggregation step, not **by** it.

This pattern is compounded when downstream consumers of the constructed object (indexing, slicing, iteration, bounds checking) also assume at least one element exists, or when overly restrictive guards elsewhere (e.g., rejecting all integer indices when only out-of-bounds ones should be rejected) mask or worsen the issue.

## Solution Strategy

### 识别信号
- 观测到的现象: `ValueError` about unpacking (e.g., "not enough values to unpack"), `IndexError` when constructing a data structure from an empty iterable, or crashes/exceptions specifically triggered by empty collection inputs that are valid in the domain
- Code patterns: `zip(*[recursive_call(x) for x in collection])`, destructuring like `a, b = zip(*items)`, or any aggregation over recursively-collected results without a preceding emptiness check
- Regression on edge cases that previously worked or that represent meaningful domain concepts (zero-length dimensions, empty containers, empty matrices)

### 解决步骤
1. **Audit all recursive aggregation functions** that collect results from child elements and combine them. Search for patterns like `zip(*[...])`, `*`-unpacking of comprehension results, or equivalent destructuring over recursively-gathered outputs.
2. **Verify three-case coverage** for each such function: (a) base case — leaf/scalar element, (b) recursive case — non-empty collection, (c) **empty collection** — the often-missing third case. If case (c) is absent, it must be added.
3. **Add an explicit early return for the empty collection case**, returning the appropriate identity/default values for the aggregation. For example, return an empty flat list paired with a shape tuple containing zero (e.g., `([], (0,))` for a 1-D structure), consistent with the library's conventions for representing empty objects.
4. **Audit downstream consumers** of the constructed object — indexing, slicing, iteration, bounds checking — to ensure they handle the zero-size case gracefully. Index validation should reject out-of-bounds access with a clear error message rather than crashing, and no code should assume at least one element exists.
5. **Check for overly restrictive guards** elsewhere that might reject valid operations on the empty object (e.g., rejecting all integer indices when only out-of-bounds ones should be rejected). These guards compound the issue and must be relaxed to permit valid interactions with zero-size objects.
6. **Ensure consistency** with the library's conventions and analogous constructs. If similar types already support empty construction, match their semantics for shape representation, error messages, and behavior.

### Why This Works
The empty collection is a **distinct algebraic case** — it is the identity element of the aggregation operation. Just as `sum([])` returns `0` and `product([])` returns `1`, the recursive aggregation over an empty collection must return the identity value for whatever combination operation is being performed. By handling it explicitly before the aggregation step, we avoid invoking undefined operations (`zip` over zero elements) and produce a well-formed result that downstream code can process uniformly. Returning a zero-extent shape preserves dimensionality information while correctly representing emptiness, following the principle of least surprise and aligning with how numerical/mathematical libraries universally represent empty collections.

## Boundary Cases
- **Empty collection at the top level**: The input itself is an empty list/container — the most direct trigger of this bug.
- **Empty collection at an intermediate nesting level**: A non-empty outer collection contains an empty inner collection (e.g., `[[1, 2], [], [3]]`), which may trigger the bug during recursion rather than at the top level.
- **All-empty nested structure**: Every sub-collection is empty (e.g., `[[], [], []]`), testing whether the aggregation of multiple empty results is handled.
- **Zero-size object interactions**: After constructing a zero-size object, operations like indexing (`obj[0]`), slicing (`obj[0:0]`), iteration (`for x in obj`), and property access (`.shape`, `.size`) must all behave correctly and produce clear error messages where appropriate.
- **Mixed valid and invalid access on zero-size objects**: Ensure that index validation rejects out-of-bounds access (e.g., `obj[0]` on an empty object) with a meaningful error, while still permitting valid operations like empty slicing or shape inspection.
- **Consistency with non-empty construction**: The empty object should be indistinguishable in type and interface from a non-empty one — only its size/shape should differ.

## PR Examples
- sympy__sympy-23117: A recursive flattening/shaping function for `Array` used `zip(*results)` to aggregate child results, crashing on empty input (`Array([])`) with a `ValueError`. The fix added explicit empty-collection handling returning a zero-length shape, and corrected downstream index validation that was overly restrictive for the zero-size case.