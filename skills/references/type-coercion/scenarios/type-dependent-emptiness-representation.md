## Problem Description

When a system uses cached or snapshot values of a related object's identifier, and a staleness check guards whether that cached value should be refreshed, the check may only recognize one form of "empty/unset" (e.g., `None`) while ignoring other type-dependent empty representations (e.g., `""` for string fields, `0` for certain numeric contexts). This causes the stale, empty value to be treated as a legitimate populated value, silently persisting incorrect data instead of refreshing from the actual current state of the related object.

This pattern generalizes beyond ORM foreign keys to any scenario where a sentinel-based "is this value populated?" check is hard-coded against a single empty representation, but the underlying data type has a different canonical form of emptiness.

## Root Cause Analysis

Different data types represent "uninitialized" or "empty" differently. Integer/auto-increment fields use `None`/null as their unset sentinel, while string-based fields use `""` (empty string), and other types may have their own conventions. When a staleness or validity check is written against only one sentinel value — typically the one used by the most common type — it silently passes through the empty representations of all other types as if they were valid, populated values.

The underlying cognitive trap is **majority-case generalization**: the developer writes the check for the dominant use case (e.g., integer primary keys where unset means `None`) and never encounters failures because that case works perfectly. The check only breaks for less common field types whose emptiness representation differs, and the failure mode is silent data corruption rather than an explicit error, making it extremely difficult to detect.

The correct abstraction is to delegate the "what counts as empty" decision to the type/field itself, since each type knows its own semantics. This makes the check polymorphic and resilient across all possible underlying types.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss**: A cached identifier (e.g., foreign key column) is persisted as an empty string or other type-specific empty value instead of the actual populated value from the related object.
  - **Inconsistent state**: The parent object's stored foreign key does not match the related object's actual primary key, even though the related object's key was set before the parent was saved.
  - The bug only manifests with non-default field types (e.g., string-based primary keys) while the common case (auto-increment integers) works correctly.
  - No error is raised — the incorrect value is silently accepted and stored.

### 解决步骤
1. **Locate the staleness/population check**: Find the condition that determines whether a cached or snapshotted value is considered "not yet populated" and therefore needs to be re-read from the authoritative source (e.g., the related object's current primary key).
2. **Audit the sentinel values**: Confirm whether the check only tests for a single hard-coded sentinel (e.g., `value is None`) rather than accounting for all type-dependent empty representations.
3. **Replace with a type-aware emptiness predicate**: Substitute the hard-coded sentinel check with the field's or type's own definition of empty values. For example, use a field-level `empty_values` list, an `is_empty()` method, or an equivalent polymorphic emptiness predicate so that `None`, `""`, empty collections, and any other type-specific empty forms are all recognized as "not yet populated."
4. **Test across type boundaries**: Write tests covering at least:
   - The default/common type (e.g., auto-increment integer PK where unset = `None`)
   - An alternative type (e.g., string-based PK where unset = `""`)
   - Verify that in both cases, the cached value is correctly refreshed before persistence.

### Why This Works

By delegating the emptiness check to the type or field definition itself, the staleness guard becomes polymorphic — it automatically adapts to whatever "empty" means for the specific data type in use. This eliminates the implicit assumption that all types share the same sentinel value and ensures correctness across the full space of possible field types without requiring the guard logic to enumerate every possible empty representation.

## Boundary Cases
- **Custom primary key types** with non-obvious empty representations (e.g., UUID fields where unset might be `None` but a zero UUID could also be considered empty in some contexts).
- **Composite or multi-field keys** where emptiness must be evaluated across multiple components — any single empty component may indicate an unset state.
- **Fields where `0` or `False` is a valid value**: The emptiness predicate must distinguish between "legitimately zero/false" and "unset," which requires careful field-level semantics rather than generic falsy checks.
- **Nullable string fields** where both `None` and `""` are possible but may carry different semantic meaning (null = "never set" vs. empty string = "explicitly cleared").
- **Reassignment scenarios**: If a related object's PK is set, then the parent is assigned a *different* related object whose PK is not yet set, the staleness check must correctly detect the new object's empty state even though the cached value from the previous assignment was valid.

## PR Examples
- django__django-13964