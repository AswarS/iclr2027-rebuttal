## Problem Description

When code transforms elements within a container and then reconstructs the container by calling `type(original)(transformed_iterable)`, it implicitly assumes that all subtypes of a base container share the same constructor signature. This assumption breaks for subtypes like named tuples, which expect individual positional arguments rather than a single iterable. The pattern typically surfaces as a regression after a refactor that introduced type-preserving reconstruction logic — where previously a plain base type (e.g., `tuple`) was returned, the new code attempts to preserve the original subtype, inadvertently invoking an incompatible constructor.

## Root Cause Analysis

The fundamental issue is conflating **behavioral subtyping** with **construction-protocol equivalence**. An `isinstance(x, tuple)` check confirms that an object behaves like a tuple (Liskov substitution principle), but it says nothing about whether `type(x)(single_iterable)` will work the same as `tuple(single_iterable)`. Named tuples, for example, override `__new__` to accept N individual positional arguments matching their field definitions, making the standard `tuple(iterable)` construction pattern fail with a `TypeError` about missing positional arguments.

This is a category error: the **consumption interface** (how the object is used after creation) and the **creation interface** (how the object is constructed) are independent properties. Subtypes are free to change their constructor signature while remaining fully compatible at the behavioral level. Any generic reconstruction logic that calls `type(value)(...)` on a polymorphic container must account for this constructor-signature variance across the type hierarchy.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` citing missing positional arguments or unexpected constructor signatures when processing containers
  - Regression appearing after a refactor that added type-preserving reconstruction (previously returned plain `tuple`/`list`, now calls `type(original)(...)`)
  - Crash occurs specifically with named tuples or custom container subclasses, while base types work fine
  - Error manifests in data transformation pipelines, query construction, or serialization paths that iterate and rebuild containers

### 解决步骤
1. **Locate reconstruction sites**: Search the codebase for patterns like `type(value)(generator_or_iterable)` or `type(value)(transformed_elements)` where the container type is dynamically determined.
2. **Audit subtype constructor compatibility**: For each site, determine whether subtypes of the expected base container could have different constructor signatures. Named tuples are the most common case for tuples; custom `list` or `dict` subclasses may also diverge.
3. **Add subtype detection logic**: Use duck-typing conventions to detect subtypes with incompatible constructors. For named tuples, check `hasattr(type(value), '_make')` — the `_make` classmethod is the standard "construct from iterable" factory method that named tuples provide.
4. **Branch the reconstruction logic**:
   - If the subtype provides a factory method (e.g., `_make`), use it: `type(value)._make(resolved_elements)`
   - Alternatively, unpack resolved elements as positional arguments: `type(value)(*resolved_elements)`
   - For the base type or compatible subtypes, continue using the single-iterable constructor: `type(value)(resolved_elements)`
5. **Add regression tests**: Cover both plain containers and subtyped containers (especially named tuples) to ensure the reconstruction logic handles all variants and to prevent future regressions.

### Why This Works

Named tuples specifically provide the `_make` classmethod as the canonical way to construct an instance from an iterable, precisely because their regular constructor expects individual positional arguments. By detecting this protocol via `hasattr` and dispatching accordingly, the reconstruction logic respects the actual creation interface of each subtype rather than assuming uniformity. This approach follows the principle that **polymorphic construction requires explicit protocol negotiation** — you cannot blindly call a constructor through a type variable without understanding its signature contract.

## Boundary Cases

- **Named tuples with default values**: Some named tuple definitions include defaults for trailing fields. Unpacking via `*resolved_elements` or using `_make` still works, but ensure the element count matches the field count exactly when using `_make` (it does not apply defaults).
- **Deeply nested containers**: If the transformation is recursive, every level of nesting must apply the same subtype-aware reconstruction logic, not just the outermost container.
- **Custom subclasses with `__init__` side effects**: Some container subclasses add validation or transformation in `__init__`/`__new__`. Using `_make` or `*args` unpacking may bypass or trigger these differently than expected.
- **Third-party named-tuple-like classes**: Libraries may define tuple-like classes without `_make`. The fallback of `type(value)(*elements)` handles these, but classes expecting keyword arguments will still fail — consider a try/except fallback to the base type as a last resort.
- **Empty containers**: Ensure the reconstruction logic handles zero-element containers correctly, as `type(value)(*[])` and `type(value)._make([])` may behave differently for types with required fields.

## PR Examples

- **django__django-13590**: Django's query resolution logic was updated to preserve the original container type when resolving `OuterRef` expressions inside tuples. This broke named tuple parameters because `type(value)(resolved_iterable)` was called, but named tuples require `_make` or positional unpacking instead of a single iterable argument.