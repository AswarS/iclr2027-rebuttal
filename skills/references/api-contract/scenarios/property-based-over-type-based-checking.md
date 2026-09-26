## Problem Description

When validation logic uses `isinstance` checks against specific concrete types to reject invalid inputs, it creates an implicit assumption that the listed types are the *only* representations of the invalid category. In systems with multiple internal representations for semantically equivalent entities—such as ORMs with forward relations, reverse relations, proxy models, or plugin-generated field types—some representations inevitably bypass the type-based guard. The result is that structurally similar invalid inputs slip through validation and produce opaque runtime errors instead of clear, early validation messages.

This pattern is especially prevalent in frameworks and libraries where the object model evolves over time: new relation types, new field wrappers, or new proxy objects are introduced that share the disqualifying semantic property but do not share a common base class with the types originally checked.

## Root Cause Analysis

The underlying principle is **conflating known concrete types with the full semantic category they represent**. When a developer writes `isinstance(obj, (ManyToManyField, ManyToManyRel))`, their mental model implicitly assumes these are the only ways a "many-to-many relation" can appear. But the actual invariant being enforced is a *semantic property*—"this field represents a one-to-many or many-to-many relation"—not a *type identity*.

This is a form of **incomplete abstraction**: the guard encodes knowledge about *which classes exist today* rather than *what property makes the input invalid*. As the system evolves and new representations emerge (e.g., `ForeignObject` subclasses, reverse relation descriptors, dynamically generated field types), the type-based check becomes stale while the semantic property remains stable. The cognitive trap is that the original check works for all known cases at the time of writing, giving a false sense of completeness.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A validation check catches *some* invalid inputs at startup/configuration time but lets structurally similar inputs through, producing crashes or opaque runtime errors when those inputs are exercised.
  - Error messages reference internal framework types (e.g., `AttributeError`, `FieldError`) rather than the clear validation message that exists for the "known" invalid cases.
  - The failing input shares a semantic property (e.g., "is a relation", "is many-to-many") with inputs that *are* correctly rejected, but differs in its class hierarchy.

### 解决步骤
1. **Identify the semantic property** that makes the input invalid. Ask: "What characteristic of this object causes it to be disallowed?" Express this as a predicate over attributes or protocols, not over types. For example: "the field is a relation *and* that relation is one-to-many or many-to-many."
2. **Replace `isinstance` checks with attribute-based or protocol-based checks** that query the semantic property directly. Use expressions like `getattr(obj, 'is_relation', False) and (obj.many_to_many or obj.one_to_many)` instead of `isinstance(obj, (ManyToManyField, ManyToManyRel))`.
3. **Use `getattr` with safe defaults** when querying attributes that may not exist on all objects passing through the validation path. This prevents introducing new `AttributeError` crashes for non-matching inputs that lack the queried attribute.
4. **Enumerate all known representations** of the semantic category and write targeted test cases for each one. Include forward relations, reverse relations, proxy objects, and any framework-specific variants to verify the new check covers the full category.
5. **Preserve legacy checks for backward compatibility** if downstream code or error messages depend on distinguishing specific types, but ensure the new broader property-based check is the primary guard that runs first.

### Why This Works

Attribute-based and protocol-based checks test **what the object means** rather than **what class it is**. This aligns the validation guard with the actual invariant being enforced. When a new type is introduced that shares the same semantic property, it automatically satisfies (or fails) the property-based check without requiring any modification to the validation code. This makes the guard resilient to framework evolution and eliminates the maintenance burden of tracking every new concrete type that represents the same concept.

## Boundary Cases
- **Objects that lack the queried attribute entirely**: Non-field objects or primitive values passed through the same code path may not have `is_relation`, `many_to_many`, etc. Always use `getattr(obj, 'attr', False)` or `hasattr` to avoid replacing one crash with another.
- **Fields that are relations but are intentionally allowed**: Some relation types (e.g., `ForeignKey` / many-to-one) may be valid inputs. The property-based check must be precise enough to distinguish allowed relations from disallowed ones (e.g., checking `one_to_many or many_to_many` rather than just `is_relation`).
- **Third-party or dynamically generated field types**: Plugin systems may produce field objects that set semantic attributes inconsistently. The check should degrade gracefully (default to "allowed") rather than crash when attributes are missing.
- **Backward compatibility with custom `isinstance` overrides**: Some frameworks allow `__instancecheck__` customization. Switching away from `isinstance` may change behavior for code relying on such overrides; verify no downstream contracts are broken.

## PR Examples
- django__django-16816