## Problem Description

When a function parameter serves as a multi-state switch — where `None` means "not provided/use default," `False` means "explicitly disabled," `True` means "explicitly enabled," and a structured value like `dict` means "enabled with configuration" — using `if param is not None` as the activation guard incorrectly treats an explicit opt-out (`False`) the same as an explicit opt-in (`True`). This leads to features being partially activated when the user intended to disable them, manifesting as spurious warnings, unexpected side effects, or incorrect behavior on edge cases that were previously working.

## Root Cause Analysis

The root cause is a semantic conflation between **parameter presence** and **parameter intent**. The `is not None` idiom correctly answers the question "did the caller provide a value?" but it does **not** answer the question "does the caller want this feature turned on?" When a parameter's purpose is to toggle a feature, these are fundamentally different questions. An explicit `False` is a deliberate opt-out — it is semantically the opposite of `True` — yet `is not None` evaluates both to `True`, funneling them into the same activation code path.

This pattern is especially insidious when:
- The default behavior (when `None` is passed) already does not activate the feature, making `False` appear redundant in normal usage.
- A refactor introduces or tightens the `is not None` guard, causing a regression on the `False` path that previously worked by accident or through a different code structure.
- Downstream code (e.g., validation, warning emission, state inspection) assumes that if the activation path was entered, the feature is genuinely enabled — leading to incorrect error messages or warnings when the value is actually `False`.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Users receive incorrect warnings or error messages when explicitly passing a disabling value (e.g., `feature=False`).
  - A regression appears after a refactor that introduced or changed an `is not None` guard.
  - Behavior differs between omitting a parameter entirely (`func()`) and explicitly disabling it (`func(feature=False)`), when both should produce the same outcome.
  - Code review reveals `if param is not None:` guarding feature activation for a parameter documented as accepting `bool`, `dict`, or `None`.

### 解决步骤
1. **Audit parameter semantics**: Identify all parameters that function as tri-state (`None`/`False`/`True`) or quad-state (`None`/`False`/`True`/`dict`) switches. Document the intended meaning of each state explicitly.
2. **Replace `is not None` with a precise dispatch**: Restructure the conditional logic to first check for structured types (`isinstance(param, dict)`), then check truthiness (`if param:`), allowing falsy values like `False`, `0`, or `""` to fall through without activating the feature. Reserve the `None` case for the default/fallback path.
3. **Ensure explicit `False` definitively disables**: Verify that when `False` is passed, no feature state is set, no engine is installed, no downstream validation or warning logic is triggered — the feature is completely inert.
4. **Add comprehensive branch tests**: Write test cases covering all parameter states — `None`, `False`, `True`, and structured config (e.g., `dict`) — asserting that only truthy and structured values activate the feature, that `False` produces no side effects, and that `None` follows the expected default path.

### Why This Works

The fix aligns the code's branching logic with the parameter's semantic contract. By testing truthiness rather than mere presence, the guard correctly maps the user's intent: `False` means "off" and falls through the activation path, while `True` and structured values mean "on" and enter it. The `None` sentinel retains its role as "not specified, use default." This eliminates the category error of treating "the user said something" as equivalent to "the user said yes."

## Boundary Cases
- **`False` vs `None` equivalence**: When the default behavior for `None` is "feature off," passing `False` should produce identical behavior — no warnings, no partial state, no observable difference.
- **Falsy non-boolean values**: Parameters that accept `0`, `""`, or empty collections as valid disabling values must not trigger activation. The guard must handle all falsy types, not just `False`.
- **`True` vs structured value**: When `True` means "enable with defaults" and a `dict` means "enable with custom config," the dispatch must distinguish these (e.g., `isinstance` check before truthiness check) to avoid treating `True` as a dict or vice versa.
- **Sentinel vs `None`**: In cases where `None` is a valid user-provided value (not just "unset"), a dedicated sentinel object (e.g., `_UNSET = object()`) should be used as the default, keeping `None` available as an explicit user choice.
- **Backward compatibility**: If prior behavior allowed `False` to work correctly (by accident or different code structure), the fix must restore that behavior without breaking the `True` or `dict` paths.

## PR Examples
- matplotlib__matplotlib-23987: A parameter accepting `None`/`False`/`True`/`dict` used `is not None` to guard feature activation, causing explicit `False` to trigger warnings and incorrect behavior that did not occur when the parameter was simply omitted.