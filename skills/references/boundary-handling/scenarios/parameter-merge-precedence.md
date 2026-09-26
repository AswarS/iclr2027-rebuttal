## Problem Description

When a factory or builder method constructs objects using a combination of user-supplied keyword arguments (typically configured at a broad scope) and internally-fixed keyword arguments (enforcing invariants for a specific construction path), Python's `**kwargs` unpacking semantics can cause `TypeError: got multiple values for keyword argument` crashes. This occurs because the developer implicitly assumes the user-supplied parameter set and the internally-controlled parameter set are always disjoint — an assumption that breaks when users legitimately configure parameters at a collection-wide level that happen to overlap with parameters a specific construction path needs to fix.

## Root Cause Analysis

The root cause is an **implicit assumption of disjointness** between two sets of keyword arguments combined in a single constructor call. Python distinguishes between two ways of passing keyword arguments:

1. **Explicit keyword arguments**: `Constructor(fixed_param=fixed_value)`
2. **Unpacked dictionary arguments**: `Constructor(**user_kwargs)`

When both are used in the same call and a key appears in both, Python raises a `TypeError` — it does not silently resolve the conflict. The developer's mental model treats these as separate, non-overlapping concerns (user config vs. internal invariants), but at runtime they collapse into a single namespace where collisions are fatal.

This is fundamentally an **ordering-dependency** and **implicit-assumption-violation** problem. The user-supplied dictionary is set at a higher scope (e.g., collection-level configuration applied to all items), while the fixed parameters are set at a lower scope (e.g., a sentinel or special-case instance). The user has no visibility into which construction paths exist internally and cannot reasonably be expected to exclude keys that conflict with internal invariants.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError: <Constructor>() got multiple values for keyword argument '<param>'` at runtime
  - The crash is a **regression triggered by edge-case configuration** — it only manifests when a user-supplied kwargs dictionary (set at a broad scope) contains a key that a specific internal construction path also sets explicitly
  - The crash does **not** occur for the common-case construction paths, only for special-case or sentinel instances

### 解决步骤
1. **Audit all construction paths** where the framework passes both user-supplied kwargs (`**user_kwargs`) and internally-fixed kwargs as explicit keyword arguments to the same constructor or function call.
2. **Identify overlap potential**: Determine whether any of the internally-fixed parameter names could plausibly appear in the user-supplied dictionary — especially when that dictionary is configured at a scope broader than the individual construction call (e.g., collection-level defaults applied to each item).
3. **Restructure using dictionary merge semantics**: Replace `Constructor(**user_kwargs, fixed_param=fixed_value)` with `Constructor(**{**user_kwargs, 'fixed_param': fixed_value})`. This ensures fixed/invariant values silently override any conflicting user-supplied values via Python's dictionary merge behavior (last writer wins).
4. **Alternative approach**: If the merge idiom is not idiomatic in the codebase, create a shallow copy of the user-supplied dictionary and pop/remove known conflicting keys before unpacking: `cleaned = {**user_kwargs}; cleaned.pop('fixed_param', None); Constructor(**cleaned, fixed_param=fixed_value)`.
5. **Do NOT raise an error** for the overlap. The user sets kwargs at a broad scope and should not be forced to handle special-case exclusions they have no visibility into.

### Why This Works

Python's dictionary merge (`{**dict_a, **dict_b}`) resolves key collisions by letting the second dictionary's values win. This is exactly the correct semantics when the second set of values represents authoritative, invariant parameters that must hold regardless of user input. By unpacking user-supplied kwargs first and placing fixed kwargs second in the merged dictionary, the fixed values are guaranteed to take precedence. This eliminates the `TypeError` while preserving the intended invariant — the user's broad-scope configuration is respected everywhere it can be, and silently overridden only where the framework requires specific values.

## Boundary Cases
- **User-supplied dictionary is empty**: The merge produces only the fixed kwargs — no behavioral change, no error.
- **User-supplied dictionary contains ALL of the fixed keys**: All conflicting values are silently overridden — the special-case construction path's invariants are preserved without error.
- **User-supplied dictionary contains keys not used by the constructor at all**: These will still propagate and may cause their own `TypeError` for unexpected keyword arguments — this is a separate validation concern and should not be conflated with the merge-precedence fix.
- **Multiple special-case construction paths with different fixed keys**: Each path must independently ensure its fixed keys take precedence; a single global cleanup is insufficient if different paths fix different parameters.
- **Mutable user-supplied dictionary**: If the original dictionary must not be modified (it may be reused across construction calls), always operate on a copy (`{**user_kwargs, ...}` inherently creates a new dict).

## PR Examples
- **django__django-16041**: A formset's `empty_form` construction path fixed certain parameters (e.g., `empty_permitted`) while also unpacking user-supplied `form_kwargs` configured at the formset level, causing `TypeError` when users included the same key in their global form kwargs.