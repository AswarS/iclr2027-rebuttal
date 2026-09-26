## Problem Description

When a system stores callable objects and later extracts identity information (such as `__name__`, `__module__`, `__qualname__`) for representation, naming, routing, or debugging purposes, composite wrapper objects like `functools.partial` break the expected contract. These wrappers encapsulate an underlying function with pre-bound arguments but do not expose the standard identity attributes that downstream code assumes all callables possess. If the wrapper is stored directly without unwrapping, any attempt to access identity attributes will fail with `AttributeError` or produce meaningless results, causing incorrect output across the entire system — not just in display logic.

## Root Cause Analysis

The root cause is an **implicit assumption** that all callable objects carry standard function identity attributes (`__name__`, `__module__`, `__qualname__`). This assumption holds for regular functions, methods, and lambdas, but fails for composite wrappers like `functools.partial`, which are callable but are not functions — they are descriptor-less objects that delegate invocation to an inner `func` attribute while lacking the metadata attributes of that inner function.

The deeper principle is that **identity and behavior are conflated** when a wrapper is stored as-is. The wrapper preserves calling behavior (it will invoke the right function with the right arguments) but discards calling identity (who the function is, where it came from). Systems that need both must decompose the wrapper at the point of storage — not at the point of consumption — because multiple consumers may independently need the identity, and patching each consumer is fragile and incomplete.

This is an instance of the **incomplete abstraction** pattern: the abstraction boundary (accepting "any callable") is broader than the implementation's actual requirements (a callable *with function-like metadata*). The fix narrows the gap by normalizing the input at the boundary.

## Solution Strategy

### 识别信号
- 观测到的现象: Wrong output, `AttributeError` on `__name__`/`__module__`/`__qualname__`, or unhelpful/missing display names when `functools.partial` objects are passed as callables through a dispatch, routing, or resolution system.
- Representation or naming methods produce errors or empty strings for partial-wrapped callables.
- The problem manifests not just in one display path but across multiple consumers of the stored callable's identity.

### 解决步骤
1. **Detect the wrapper at initialization time**: In the constructor or initialization method where the callable is first received and stored, check whether the incoming callable is an instance of `functools.partial`.
2. **Unwrap the composite**: Extract the underlying function from `partial.func` and use it as the canonical callable to store. This restores access to all standard identity attributes (`__name__`, `__module__`, `__qualname__`).
3. **Merge bound arguments**: Prepend the partial's positional arguments (`partial.args`) to the existing positional arguments, and merge the partial's keyword arguments (`partial.keywords`) into the existing keyword arguments, respecting appropriate precedence (typically, explicitly provided kwargs override the partial's defaults).
4. **Store the unwrapped function and merged arguments**: Replace the original callable reference with the unwrapped function and the combined argument sets, so all downstream consumers see a clean, fully-attributed function with complete invocation semantics.
5. **Validate with end-to-end tests**: Write tests that pass `functools.partial`-wrapped callables through the full pipeline and assert correctness of: the stored callable reference, the merged args/kwargs, the display name, and any other identity-derived outputs.

### Why This Works

Unwrapping at initialization — the point where identity is *established* — ensures that every downstream consumer inherits a correct, consistent view of the callable's identity without needing individual patches. The merged arguments preserve the full calling semantics: the stored positional and keyword arguments, combined with the partial's pre-bound arguments, represent the complete invocation contract. This approach treats the wrapper as a *transport encoding* that must be decoded once at the boundary, rather than as a permanent representation that every reader must know how to interpret.

## Boundary Cases
- **Nested partials**: A `functools.partial` wrapping another `functools.partial`. The unwrapping logic should recursively unwrap until a non-partial callable is reached, accumulating arguments at each level.
- **Partial wrapping a class or other callable**: The inner `func` might be a class with `__init__`/`__call__` rather than a plain function. Ensure identity extraction handles this gracefully.
- **Empty or conflicting kwargs**: When both the partial's `keywords` and the system's own kwargs define the same key, the precedence rule must be clearly defined and documented.
- **Decorated functions**: The underlying function may itself be wrapped by decorators (e.g., `@functools.wraps`). Unwrapping the partial should be sufficient; further unwrapping through decorator layers is typically unnecessary since `@wraps` copies identity attributes.
- **Partial with no extra arguments**: A `functools.partial(func)` with no bound args should degrade cleanly to storing `func` with unchanged arguments.

## PR Examples
- django__django-14155