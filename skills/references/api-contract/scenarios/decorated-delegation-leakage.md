## Problem Description

When a public method delegates to another public method on the same class for code reuse, and the delegated-to method has framework-level decorators or interceptors that transform its return type (e.g., converting a raw array into a DataFrame based on global configuration), the calling method receives an unexpected type. This causes crashes, type errors, or subtle data corruption that only manifests when specific configuration flags are enabled — making the bug intermittent and environment-dependent. The core issue is a **leaky abstraction**: the decorator's behavioral modification, intended only for external consumers, silently propagates into internal computation paths.

## Root Cause Analysis

Public methods in frameworks often serve dual roles: they contain reusable computation logic **and** act as decorated API endpoints whose output format can be externally modified by configuration, middleware, or interceptors. When a developer treats a public method as a stable internal function and delegates to it from another public method, they inadvertently inherit the invisible behavioral layer imposed by decorators.

The fundamental principle violated is **separation of computation from presentation**. A public method decorated with an output-format transformer (e.g., `set_output` in scikit-learn that wraps NumPy arrays as pandas DataFrames) is no longer a pure computation — it is a context-sensitive API endpoint. The mental model of "these two methods compute the same thing, so one can call the other" breaks down because the decorator creates an implicit assumption violation: the caller expects a raw type, but receives a transformed type that depends on global or contextual state.

This is particularly insidious because:
- The bug is **configuration-dependent** — it only appears when a specific flag (e.g., `transform_output="pandas"`) is enabled
- The delegation path looks perfectly reasonable in code review
- Tests that don't activate the configuration flag will pass, masking the defect

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `AttributeError` crashes when a global configuration flag is enabled (e.g., `set_config(transform_output="pandas")`)
  - A method receives a DataFrame/wrapped object where it expects a plain NumPy array
  - The failure is **intermittent** — it depends on environment configuration or test ordering
  - Stack traces show one public method calling another public method on the same class, where the callee has framework-level decorators

### 解决步骤
1. **Audit delegation chains**: Identify all public methods that delegate to other public methods on the same object. Flag cases where the target method has decorators, interceptors, or framework-level wrappers that can alter return types.
2. **Extract shared logic into a private method**: Create a private method (prefixed with `_`) that contains the raw computation logic. This method must **not** be subject to any output-format interceptors or decorators. It returns the raw, undecorated result.
3. **Rewire the public method**: Redefine the original public (delegated-to) method as a thin wrapper around the new private method. The public method preserves its API contract and allows framework decorators to apply only at this boundary.
4. **Redirect the delegating method**: Change the calling method to invoke the private method directly, bypassing any output-format wrapping applied to the public API surface.
5. **Validate return type stability**: Add assertions or tests confirming that the private method's return type is stable and unaffected by any global configuration or context-dependent transformations. Test with all relevant configuration flags both enabled and disabled.

### Why This Works

Extracting shared logic into a private method creates a **stable internal computation path** that is immune to external behavioral modifications. The decorated behavior is preserved only at the intended public API boundary — where external consumers expect it. This enforces the principle: **never delegate between public API methods for internal computation; always factor shared logic into a private, undecorated implementation.**

The private method acts as a "clean room" that guarantees type stability regardless of framework configuration, while the public methods remain thin, decorated shells that transform output for external consumers.

## Boundary Cases
- **Chained decorators**: Multiple decorators on the public method may each transform the output; the private method must bypass all of them, not just the most visible one.
- **Subclass overrides**: If a subclass overrides the public method, the private method extraction must ensure subclasses can still customize computation without re-introducing the decorator leakage.
- **Multiple delegation hops**: Method A calls Method B calls Method C — if any method in the chain is decorated, the entire chain must be audited and potentially refactored to use private methods.
- **Decorator applied via metaclass or mixin**: The decorator may not be visible in the class definition itself (e.g., applied by a parent class's `__init_subclass__` or a metaclass), making the leakage harder to detect through code inspection alone.
- **Testing coverage gap**: Ensure tests exercise the code path with **all** relevant configuration flags enabled; the default configuration often masks the bug entirely.

## PR Examples
- scikit-learn__scikit-learn-25500