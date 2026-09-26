## Problem Description

When serializing enumeration values in systems that support flag-style enums (where valid values can be formed by bitwise-OR combinations of named members), a serializer that assumes every valid value maps to a single symbolic name will produce invalid output for composite values. The composite value has no single `.name` — the name lookup returns `None` or an equivalent null sentinel — resulting in silent data corruption in serialized artifacts such as migration scripts, configuration files, or data interchange formats.

This is a **composite-value serialization** problem: the serialization layer embodies an implicit assumption that the value domain and the name domain are bijective (one-to-one), when in reality flag enums define an algebraic value space far larger than the set of individually named members.

## Root Cause Analysis

Flag-style enumerations define a small set of **named primitive members**, but through bitwise combination they implicitly define a combinatorial space of **valid composite values**. A serializer written for simple (non-flag) enums naturally uses a pattern like `EnumType[value.name]` or `value.name` to produce a symbolic reference. This works perfectly when every value in the domain has exactly one canonical name.

The root cause is an **incomplete abstraction**: the serializer treats all enum types uniformly, not recognizing that flag enums have a fundamentally different relationship between values and names. A composite flag value (e.g., `Permission.READ | Permission.WRITE`) is a first-class valid value of the enum type, but it has no single name — it was *constructed* by combining named primitives. The serializer must mirror that construction in its output.

A secondary complication is that the runtime API for decomposing composite flag values into their named constituents may differ across language/framework versions, meaning a correct fix must also account for version-dependent iteration behavior.

## Solution Strategy

### 识别信号
- 观测到的现象: Serialized output (e.g., migration files, JSON, configuration) contains `None`, `null`, or an invalid/unresolvable symbolic reference where a valid enum expression was expected
- Composite flag values silently lose their meaning — the serialized form cannot be deserialized back to the original value
- The problem manifests only for combined flag values; single named members serialize correctly, making the bug intermittent and hard to catch without targeted tests

### 解决步骤
1. **Classify the enum type**: Determine whether the enum being serialized is a flag-style enum (supports bitwise combination) or a simple enum (each value has exactly one name). This distinction gates the serialization path.
2. **Decompose composite values**: For flag-style enums, decompose the composite value into its individual named constituent members. Use the appropriate runtime API for decomposition, branching on runtime version if the API changed across versions (e.g., Python 3.10 vs 3.11 changed `Flag.__iter__` behavior).
3. **Serialize each constituent by name**: Map each individual named member to its fully-qualified symbolic reference (e.g., `ModuleName.EnumType["MEMBER_NAME"]`).
4. **Join with the composition operator**: Combine the individual serialized references using the bitwise-OR operator (`|`) to produce a single valid expression that reconstructs the original composite value when evaluated.
5. **Unify code paths where possible**: Treat a single named value as a degenerate case of composition (a collection of one), allowing both flag and non-flag paths to share the join logic and minimizing code divergence.
6. **Preserve backward compatibility**: For non-flag enums, retain the existing single-name serialization path unchanged to avoid regressions.

### Why This Works

Serialization must mirror construction. If a value was built by combining named primitives with bitwise-OR, its serialized form must express that same combination. The resulting expression (e.g., `Type["A"] | Type["B"]`) is both human-readable — matching how developers write combined flags in source code — and mechanically correct, producing the original value when evaluated. By decomposing into named constituents, we guarantee that every component has a valid symbolic name, sidestepping the fundamental problem that composite values lack a single name.

## Boundary Cases
- **Zero/empty flag value**: Some flag enums define a zero-valued member (e.g., `Flags.NONE = 0`). Decomposition must handle this correctly — iterating over a zero-valued flag may yield an empty sequence, requiring special-case handling to emit the zero member's name.
- **Single named member that happens to be a flag enum**: Must still serialize correctly via the same path (degenerate single-element composition).
- **Aliased members**: Flag enums may define aliases (e.g., `ALL = READ | WRITE | EXECUTE`). The serializer should prefer decomposition into primitive members rather than using the alias name, unless the alias is the canonical representation.
- **Runtime version differences**: Decomposition APIs (e.g., `__iter__` on flag values) may behave differently across runtime versions. The solution must detect and branch accordingly.
- **Negative or inverted flags**: Some flag systems support complement operations (`~Flag.READ`). These produce values that may not decompose cleanly into named positive members and require additional handling.

## PR Examples
- django__django-15996