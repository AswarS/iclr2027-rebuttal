## Problem Description

When a save/restore mechanism (such as a context manager) captures configuration state on entry and restores it on exit, it implicitly assumes that restoring a value to its original is a no-op. However, in configuration systems where certain keys have write-triggered side effects — such as clearing global registries, reinitializing subsystems, or tearing down accumulated runtime state — the act of *setting* a value (regardless of whether it changed) triggers destructive operations. This means that runtime state legitimately created between the save and restore points (e.g., registered objects, cached entries) is silently destroyed upon context exit, even though the configuration value itself hasn't changed.

This is a specific instance of the **idempotency assumption violation** pattern: code assumes `config[key] = config[key]` is harmless, but setter hooks make every write stateful and potentially destructive.

## Root Cause Analysis

The underlying principle violated is **idempotency of assignment**. In a plain data structure, assigning a value to itself is always a no-op. But configuration systems often layer validation, event dispatch, or side-effect hooks on top of assignment. When a key's setter triggers operations like "clear all registered backends" or "reinitialize the font subsystem," every write — including a write of the same value — executes those operations.

The cognitive trap is **restoration-is-harmless thinking**: developers naturally reason that "putting things back the way they were" cannot cause damage. This reasoning holds for pure data but breaks down when the *act of writing* carries semantic weight independent of the *value being written*. The save/restore abstraction leaks because it treats all configuration keys uniformly, ignoring that some keys are not merely data but are control signals with imperative side effects.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss**: Objects registered in a global registry during a context block disappear after the context exits, with no error or warning
  - **Inconsistent state**: Subsystems appear uninitialized or reset after a context manager exits, despite no explicit change to their configuration
  - **Non-reproducible behavior**: Code works when run at module level but fails when wrapped in a configuration context manager
  - **Setter hooks firing unexpectedly**: Logging or debugging reveals that configuration setters execute during restore even when the value hasn't changed

### 解决步骤
1. **Audit the configuration system's setter/validator hooks** to identify which keys have write-triggered side effects (initialization, teardown, registry clearing, subsystem reloading). Build an explicit list of these "side-effect keys."
2. **Exclude side-effect keys from the restore cycle** in the save/restore mechanism. Do not attempt to restore keys whose restoration would trigger destructive operations, even if the value is unchanged.
3. **Convert saved state to a plain container type** (e.g., a plain `dict` instead of a custom config object) during the save phase. This prevents validation or setter hooks from firing when the snapshot is constructed or when values are read back during restore.
4. **Document the exclusion explicitly** so that users of the context manager understand that certain settings are intentionally not restored, and why.
5. **Add regression tests** that create runtime state (e.g., register objects in a global registry) inside the context block and verify that this state survives context exit. Follow the context exit with a read of the excluded setting to confirm no side effects occurred.

### Why This Works

Excluding side-effect-bearing keys from the restore cycle eliminates the destructive write entirely, which is fundamentally safer than trying to make the side effects conditional on value change. Making side effects truly idempotent would require modifying the setter logic to compare old and new values before acting — but this logic may be complex, shared across multiple code paths, and fragile to changes. The exclusion approach is a **minimal, localized fix** that respects the existing side-effect semantics without attempting to re-engineer them. It converts the save/restore mechanism from "restore everything blindly" to "restore only what is safe to restore," which is a more honest contract with the caller.

## Boundary Cases

- **Keys whose side effects are conditionally destructive**: Some keys may only trigger side effects when set to certain values, not on every write. These require case-by-case analysis — blanket exclusion is the safe default, but finer-grained logic may be warranted if the key is commonly expected to be restored.
- **Nested context managers**: If context managers are nested and both exclude the same keys, the inner context's state changes to those keys will persist through both exits. Users must understand that excluded keys are effectively "pass-through" for all nesting levels.
- **Configuration keys added in future versions**: New keys with side effects may be introduced without updating the exclusion list. The exclusion list should be maintained alongside the configuration schema, ideally with a mechanism (e.g., a decorator or metadata flag) that marks keys as side-effect-bearing at the point of definition.
- **Partial restore failures**: If the restore process fails midway (e.g., due to an exception in a setter for a non-excluded key), the configuration may be left in a partially restored state. The restore logic should handle this gracefully, potentially using try/finally patterns.
- **Third-party extensions registering custom config keys with side effects**: External code may add keys that the core exclusion list doesn't know about. Providing an API for extensions to declare their keys as side-effect-bearing enables correct behavior without modifying core code.

## PR Examples

- **matplotlib__matplotlib-23299**: Restoring `rcParams` via a context manager triggered backend reinitialization on every exit because the backend key's setter cleared registered objects, even when the value was unchanged. The fix excluded the backend key from the restore set and converted the saved state to a plain dict.