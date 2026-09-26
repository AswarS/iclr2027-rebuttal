## Problem Description

When an object maintains both a canonical (user-specified, logical) value and a derived (runtime-adjusted) value — such as a base DPI multiplied by a display scaling factor — serializing the derived value instead of the canonical one causes the environment-dependent transformation to compound on each serialize-deserialize cycle. The derived value is treated as the new canonical input upon deserialization, and the environment re-applies its transformation, producing exponential drift (e.g., a DPI that doubles with every round-trip on a Retina display). This pattern affects any system where an environment silently mutates a value after initial assignment and the serialization layer captures the mutated snapshot rather than the original intent.

## Root Cause Analysis

The fundamental issue is a **conflation of logical state with runtime state**. When an environment (display backend, locale, timezone, scaling layer) silently transforms a user-specified value into a runtime-adjusted value, the in-memory representation of the object no longer reflects the user's original intent. If the serialization hook (`__getstate__`, `toJSON`, etc.) naively dumps the current in-memory state, it captures the already-transformed value. Upon deserialization, the constructor or initialization path re-applies the same environment-dependent transformation to what it assumes is a canonical input — but it is actually an already-derived output. Each cycle compounds the transformation:

```
Cycle 0: canonical=100, derived=100×2=200 (environment scales ×2)
Cycle 1: serialized=200, derived=200×2=400
Cycle 2: serialized=400, derived=400×2=800
```

The cognitive trap is that in many environments (e.g., non-scaled displays where the multiplier is ×1), the canonical and derived values are identical, so the bug is invisible. It only manifests in specific environments and only after multiple round-trips, making it notoriously difficult to catch without targeted testing.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A numeric property grows exponentially (doubles, triples, etc.) with each serialize-deserialize cycle, eventually causing overflow errors, visual corruption, or layout breakage.
  - The bug is **environment-dependent** — it reproduces on high-DPI/Retina displays, specific locales, or scaled monitor configurations, but not on default/unscaled environments.
  - Crash or exception after multiple round-trips (e.g., `OverflowError`, rendering failures) that cannot be reproduced with a single serialization pass.
  - Inconsistent state where a property's value after deserialization does not match the value originally set by the user.

### 解决步骤
1. **Audit the object's fields to classify each as canonical or derived.** Canonical fields represent user intent (e.g., `dpi` as specified by the user). Derived fields are computed at runtime from canonical values plus environment factors (e.g., `dpi * device_pixel_ratio`). If the canonical value is not currently tracked, introduce a field to store it at assignment time.
2. **Fix the serialization hook to emit canonical values.** In `__getstate__` (or equivalent), replace any derived values in the state dictionary with their canonical originals before returning. Use a defensive fallback pattern — e.g., `state['dpi'] = state.get('_original_dpi', state['dpi'])` — to handle objects that were serialized before the canonical field existed, preserving backward compatibility.
3. **Verify the deserialization path re-derives correctly.** Confirm that the constructor, `__setstate__`, or post-load initialization naturally re-applies the environment-dependent transformation from the canonical value. Do **not** duplicate the fix in both serialization and deserialization — this risks under-applying the transformation or introducing a different class of bug.
4. **Add a compounding round-trip test.** Serialize and deserialize the object in a loop (at least 2–3 cycles) and assert that the canonical property equals the original logical value after each cycle. Run this test under a simulated scaled environment (e.g., mock `device_pixel_ratio = 2`) to ensure the bug is exercised.

### Why This Works

The serialized representation of an object should capture its **logical intent**, not its **runtime-adjusted state**. Runtime adjustments are environment-specific side effects that will be re-applied by the environment upon restoration. By reverting to the canonical value before serialization, we break the compounding cycle: each deserialization starts from the same logical baseline, and the environment applies its transformation exactly once. The defensive fallback pattern ensures that legacy serialized objects (which lack the canonical field) degrade gracefully — they use the derived value as a best-effort canonical approximation, which is correct in unscaled environments and no worse than the previous behavior in scaled ones.

## Boundary Cases

- **Legacy deserialization**: Objects serialized before the canonical field was introduced will not have it in their state dictionary. The `get('canonical', derived)` fallback ensures these objects load without error, though the first round-trip in a scaled environment may still carry the compounded value. Document this as a known one-time migration artifact.
- **Environment changes between serialize and deserialize**: If an object is serialized on a 2× display and deserialized on a 1× display, the canonical value is correctly restored and the new environment applies its own (1×) transformation. This is the desired behavior — the object adapts to its new environment.
- **Multiplier of 1× (no scaling)**: In unscaled environments, canonical and derived values are identical, so the fix is a no-op. This is why the bug often goes undetected — the majority of CI environments and developer machines may not use display scaling.
- **Nested or composed objects**: If a parent object serializes child objects that also contain derived state, each level must independently handle its own canonical-vs-derived distinction. A fix at only the parent level will not prevent compounding in children.
- **Concurrent or partial serialization**: If an object's derived value is updated asynchronously (e.g., on a display change event) while serialization is in progress, the serialization hook must read the canonical value atomically to avoid capturing a partially-updated derived value.

## PR Examples
- matplotlib__matplotlib-23476: Figure DPI compounding on Retina/high-DPI displays across pickle round-trips, where the macOS backend doubled `fig.dpi` at runtime and the serialized state captured the doubled value.