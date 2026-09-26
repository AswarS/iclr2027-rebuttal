## Problem Description

When code serializes a class reference into a string path by combining its module (`__module__`) with its name (`__name__`), it implicitly assumes that all referenced classes are top-level members of their module. This assumption breaks for nested classes (classes defined inside other classes), producing an incorrect dotted path like `module.InnerClass` instead of the correct `module.OuterClass.InnerClass`. The resulting reference cannot be resolved at runtime, leading to `ImportError` or `AttributeError` when the serialized output (e.g., a migration file, configuration string, or serialized descriptor) is later consumed.

This is a form of **implicit assumption violation**: the serialization logic works correctly for the overwhelmingly common case (top-level classes) but silently produces wrong output for a valid, less common structural pattern (nested classes). Because the failure only manifests when the serialized artifact is *consumed* — not when it is *produced* — the bug can go undetected for a long time.

## Root Cause Analysis

The root cause is the use of a class's **simple name** (`__name__`) where its **qualified name** (`__qualname__`) is required.

- `__name__` returns only the final, unqualified identifier of a class (e.g., `Inner`).
- `__qualname__` returns the full dot-separated path from the module root through all enclosing scopes (e.g., `Outer.Inner` or `Outer.Middle.Inner`).

When serialization code constructs a reference as `f"{cls.__module__}.{cls.__name__}"`, it collapses the nesting hierarchy, producing a path that points to a non-existent top-level name. The language provides `__qualname__` specifically to solve this problem, but developers often reach for `__name__` out of habit or because the distinction is not widely understood.

A secondary contributing factor is that the **deserialization** side may also assume a flat module namespace — using only `importlib.import_module` to resolve the entire dotted path rather than walking attribute access through intermediate classes after importing the module.

## Solution Strategy

### 识别信号
- 观测到的现象: Generated code or serialized references contain paths like `module.InnerClass` that fail with `AttributeError` or `ImportError` at runtime, even though the class exists and is importable via `module.OuterClass.InnerClass`.
- Migration files, serialized configurations, or code-generated references work for top-level classes but break for any nested class.
- The error only appears when the serialized artifact is **consumed** (e.g., migration applied, config loaded), not when it is **produced**.

### 解决步骤
1. **Audit all serialization paths**: Identify every code path where a class or callable is converted to a string reference by combining `__module__` with a name attribute. Search for patterns like `cls.__module__ + "." + cls.__name__`.
2. **Replace `__name__` with `__qualname__`**: In each identified location, switch to `__qualname__`. This ensures `module.Outer.Inner` is produced instead of `module.Inner`, and it naturally handles arbitrary nesting depths with zero additional logic.
3. **Verify the deserialization path**: Ensure the corresponding import/resolution logic can handle dotted paths that traverse class hierarchies. After importing the module, it should walk remaining dotted segments via `getattr` on intermediate objects, not attempt to import the entire path as a module.
4. **Add tests for nested classes**: Create test cases with classes nested at one, two, and deeper levels. Verify that serialization produces the correct qualified path and that deserialization successfully resolves it back to the original class.
5. **Regression-proof with round-trip tests**: Confirm that serializing and then deserializing a nested class reference yields the same class object, ensuring full round-trip correctness.

### Why This Works

`__qualname__` is a language-level feature (PEP 3155) purpose-built to encode the full nesting path of a class or function from the module root. Using it instead of `__name__` is both **minimal** (a single attribute swap, no additional introspection or traversal logic) and **correct** (it handles arbitrary nesting depths and works identically to `__name__` for top-level classes, so it is a strict generalization with no regressions).

## Boundary Cases

- **Top-level classes**: `__qualname__` equals `__name__` for top-level classes, so the fix is backward-compatible and introduces no behavioral change for the common case.
- **Deeply nested classes** (e.g., `A.B.C.D`): `__qualname__` correctly encodes the full chain; deserialization must iteratively `getattr` through each level.
- **Classes defined inside functions**: `__qualname__` includes `<locals>` in the path (e.g., `func.<locals>.MyClass`), which is not importable. Serialization should detect and reject or warn about such classes, as they cannot be resolved by any import mechanism.
- **Dynamically created classes** (e.g., via `type()`): These may have a `__qualname__` that does not correspond to an actual attribute path. Serialization should validate that the path is resolvable.
- **Third-party or built-in classes**: Ensure the deserialization logic does not assume all classes come from user code; the module import + attribute walk pattern works universally.

## PR Examples

- **django__django-12125**: Django's migration serializer used `__name__` to construct references to validators and other callables in generated migration files. Nested classes produced incorrect paths, causing migrations to fail when applied. The fix replaced `__name__` with `__qualname__` in the serialization layer.