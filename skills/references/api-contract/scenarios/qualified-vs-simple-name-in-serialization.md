## Problem Description

When serializing references to callables (such as class methods used as default values) into persistent text-based representations (e.g., migration files, serialized configurations), the serialization layer constructs a fully qualified dotted path by combining the module name with the entity's name. If the code uses the entity's simple name (`__name__`) rather than its qualified name (`__qualname__`), the resulting path is incorrect and unresolvable for any callable that belongs to a nested class. This manifests as either a crash during deserialization (the path cannot be resolved) or silently wrong output (the path points to a non-existent or incorrect object).

## Root Cause Analysis

In Python, `__name__` returns only the leaf (immediate) name of a class or callable, while `__qualname__` returns the full dotted path from the module scope through all enclosing class scopes. For top-level entities, these two attributes are identical, which creates a cognitive trap: developers implicitly assume all referenced entities live at module scope. When a class is nested inside another class — a perfectly valid and common pattern (e.g., an enum or choices class defined inside a model class) — `__name__` omits the enclosing class hierarchy entirely, producing an ambiguous path like `module.InnerClass` instead of the correct `module.OuterClass.InnerClass`. The serialized path then cannot be resolved back to the original object because the intermediate scope is missing.

This is an instance of the **implicit assumption violation** pattern: the serialization abstraction assumes a flat module namespace, but the language permits arbitrary nesting depths. The abstraction is **incomplete** because it does not account for the full scope chain that Python's `__qualname__` was specifically designed to represent.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash/Exception**: Deserialization fails with an `ImportError` or `AttributeError` because the serialized dotted path cannot be resolved from the module's top-level namespace.
  - **Wrong Output**: The serialized representation contains a truncated path (e.g., `mymodule.NestedClass.method` instead of `mymodule.OuterClass.NestedClass.method`), which either silently resolves to the wrong object or fails on re-import.
  - The problem only surfaces when the callable or class being serialized is nested inside another class; top-level entities serialize correctly.

### 解决步骤
1. **Locate the serialization code** that constructs the fully qualified path for class-bound callables (methods, classmethods, static methods, or nested class references). Look for patterns where `module.__name__` is concatenated with `cls.__name__` or `func.__name__`.
2. **Audit the name attribute used**: Determine whether the code uses the simple name (`__name__`) or the qualified name (`__qualname__`) of the owning class or callable. If `__name__` is used, this is the source of the bug.
3. **Replace `__name__` with `__qualname__`** in the path construction logic. The qualified name includes the full dotted path from the module level through all enclosing class scopes down to the entity itself, ensuring the serialized path is always resolvable.
4. **Verify round-trip correctness**: Ensure that the serialized path can be resolved back to the original object by traversing `getattr` calls from the module through each component of the qualified name.
5. **Add regression tests** that serialize references to methods on nested classes (at least two levels of nesting) and verify:
   - The serialized path string is correct and fully qualified.
   - The path is resolvable from the module's top-level namespace back to the original callable.

### Why This Works

Python's `__qualname__` attribute was designed precisely to handle arbitrary nesting depths. It encodes the complete scope chain from the module level to the entity, using dot-separated names for each enclosing class. By using `__qualname__` instead of `__name__`, the serialization layer produces paths that are unambiguous regardless of how deeply nested the target entity is. This aligns the serialization abstraction with the language's own scoping model, eliminating the implicit flat-namespace assumption.

## Boundary Cases
- **Top-level classes and functions**: `__name__` and `__qualname__` are identical, so the fix is a no-op for these cases — no regression risk.
- **Deeply nested classes (3+ levels)**: The fix must handle arbitrary nesting depth, not just one level of nesting. `__qualname__` handles this naturally.
- **Lambdas and local functions defined inside methods**: These have `__qualname__` values containing `<locals>`, which are not resolvable via `getattr`. The serialization layer should detect and reject or special-case these.
- **Decorated methods or classmethods**: Ensure that the `__qualname__` is read from the underlying function, not from a wrapper that may have a different or missing `__qualname__`.
- **Dynamically created or monkey-patched classes**: These may have `__qualname__` values that do not match their actual location in the module namespace. Serialization should validate resolvability.

## PR Examples
- django__django-17087