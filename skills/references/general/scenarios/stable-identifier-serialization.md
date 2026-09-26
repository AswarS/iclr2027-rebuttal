## Problem Description

When serializing references to enumeration members into persistent artifacts (migration files, generated code, configuration snapshots), the serialization layer reconstructs the enum member by its **value** rather than its **name**. This creates a brittle coupling between the durable artifact and the runtime-resolved payload of the enum member. If the value is dynamic, translatable (e.g., `gettext_lazy`), computed, or otherwise context-dependent, the generated code will fail to round-trip correctly — producing crashes, wrong member resolution, or non-deterministic behavior across environments and locales.

This pattern generalizes beyond enums to any scenario where a symbolic constant's **identity** (its programmatic name) is conflated with its **content** (its runtime value) during code generation or serialization.

## Root Cause Analysis

The underlying principle is a **conflation of identity and content** in symbolic constants. An enum member has two distinct attributes:

- **Name**: A stable, source-code-level identifier (`MyEnum.ACTIVE` → `'ACTIVE'`). This is fixed at class definition time and never changes.
- **Value**: The payload associated with the member (`gettext_lazy('Active')`). This can be a deferred computation, a locale-sensitive string, or any object whose `repr()` or resolved form varies by context.

The cognitive trap is the implicit assumption that because an enum value *appears* as a literal in the class body, it *behaves* as a literal everywhere. In reality, values can be wrapped in lazy evaluation, derived from environment variables, or dependent on runtime state. When serialization uses value-based construction (`MyEnum(value)`), it must:

1. Recursively serialize the value itself (which may not have a stable `repr`).
2. Track imports for the value's type (e.g., `gettext_lazy`).
3. Assume the value resolves identically at deserialization time.

All three assumptions can fail. Name-based access (`MyEnum['NAME']`) sidesteps all of them by referencing the member through its immutable identity.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **crash-exception**: Generated migration files or serialized artifacts raise errors when re-evaluated (e.g., `TypeError`, `ValueError`, or import failures related to the enum value's type).
  - **wrong-output**: Enum members resolve to incorrect values or different members across locales, environments, or lazy-evaluation states.
  - Migration files contain serialized lazy translation objects, computed expressions, or environment-dependent values where a simple name-based reference was expected.

### 解决步骤
1. **Audit serialization code paths**: Identify all locations where enum members (or similar symbolic constants) are serialized into persistent text representations — migration writers, code generators, configuration serializers.
2. **Check the lookup strategy**: Determine whether the serialization reconstructs the member via its **value** (`EnumClass(member_value)`) or its **name** (`EnumClass['MEMBER_NAME']`).
3. **Switch to name-based access**: Change the serialization to emit `EnumClass['MEMBER_NAME']` using the member's `.name` attribute, which is a plain string literal.
4. **Remove value serialization overhead**: Eliminate recursive serialization of the member's value and any associated import tracking for the value's type. The only import needed is the enum class's own module.
5. **Validate round-trip correctness**: Confirm that the generated artifact, when re-evaluated in a different locale, environment, or lazy-evaluation state, resolves to the exact same enum member.

### Why This Works

Name-based serialization decouples the persistent reference from the runtime-resolved payload. The member's name is an **invariant** — it is defined once in source code and does not change across contexts. By referencing symbolic constants by their identity rather than their content, the generated artifact becomes:

- **Deterministic**: The same name always resolves to the same member.
- **Context-independent**: No dependency on locale, environment, or evaluation timing.
- **Simpler**: No need to serialize complex value types or track their imports.

This follows the broader principle: **reference things by their stable identity, not by their mutable or context-dependent content**.

## Boundary Cases

- **Enums with duplicate values (aliases)**: Multiple names can map to the same value. Name-based access preserves the *specific* alias used, whereas value-based access may resolve to the canonical (first-defined) member. Ensure the serialized name matches the originally intended member.
- **Flag enums and composite members**: Combined flag values (e.g., `MyFlag.A | MyFlag.B`) do not have a single `.name` and require decomposition into individual named members before serialization.
- **Non-enum symbolic constants**: The same pattern applies to any named constant (e.g., `namedtuple` instances, class-level sentinels) where the value is used as the serialization key instead of the attribute name.
- **Custom `_missing_` or `__new__` overrides**: Enums with custom member lookup logic may behave unexpectedly with bracket-based access; verify that `EnumClass['NAME']` still works correctly.
- **Third-party enum subclasses**: Libraries extending `enum.Enum` (e.g., Django's `TextChoices`, `IntegerChoices`) should be tested to confirm name-based access compatibility.

## PR Examples

- **django__django-11815**: Django's migration serializer reconstructed enum members by value (`EnumClass(value)`), which broke when enum values used `gettext_lazy` or other dynamic constructs. The fix switched to name-based serialization (`EnumClass['NAME']`), eliminating the dependency on value stability.