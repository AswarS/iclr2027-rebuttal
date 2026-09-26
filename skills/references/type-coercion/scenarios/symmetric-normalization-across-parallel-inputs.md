## Problem Description

When a class processes multiple parallel inputs (e.g., x/y coordinates, multiple data channels) through a multi-step initialization or property-setting method, and the attribute assignment occurs **after** a processing step that can fail (such as broadcasting, stacking, or combining inputs), an exception during that step leaves the object in a half-constructed state — missing attributes entirely. Subsequent operations (drawing, serialization, data retrieval) then raise a confusing `AttributeError` ("object has no attribute ...") instead of surfacing the original error or a meaningful message. The real bug is often an input normalization asymmetry (e.g., one input is flattened while its counterpart is not), but the user-visible symptom is a missing attribute that misdirects debugging effort entirely.

## Root Cause Analysis

This problem stems from two interacting violations:

1. **Symmetry-breaking in input normalization:** When a class accepts multiple parallel inputs that must be shape-compatible, the normalization/coercion logic may treat them asymmetrically — for example, flattening one coordinate array but not another, or applying type coercion to one channel but not its sibling. This causes downstream operations (broadcasting, stacking) to fail with shape mismatches.

2. **Implicit assumption that setup always succeeds:** Attributes are assigned only inside a setup/processing method rather than in `__init__`. The code implicitly assumes this method will always complete successfully. When the asymmetric normalization causes an exception partway through, the attribute never gets created. The object now violates its own interface contract — its methods expect attributes that don't exist.

The combination means users see an `AttributeError` at the *access site* (e.g., during rendering), with no traceback connection to the *failed initialization* or the *mismatched inputs* that caused it. This is a cascading diagnostic failure: the real cause is buried, and the visible error is maximally misleading.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `AttributeError: 'SomeClass' object has no attribute '_data'` raised during a method call (draw, serialize, etc.) that is clearly not the origin of the problem
  - The attribute in question is assigned inside a `set_*` method or a processing pipeline, not in `__init__`
  - The actual root cause is a shape mismatch, type incompatibility, or failed broadcasting between parallel inputs
  - Inconsistent state where some attributes from the setup method exist but others do not

### 解决步骤
1. **Initialize all method-expected attributes to safe defaults in `__init__`.** Add explicit assignments (e.g., `self._data = None`, `self._offsets = np.zeros((0, 2))`) in the constructor, placed **before** any call to the setup method that would assign real values. This guarantees the attribute exists on every instance regardless of downstream success or failure.

2. **Audit and fix the input normalization asymmetry.** Trace the parallel inputs through the processing pipeline and ensure symmetric treatment — if one input is flattened, squeezed, or coerced, apply the same transformation to its counterparts. Verify that all parallel inputs reach the combination step (broadcasting, stacking) in compatible shapes.

3. **Choose default values that produce clear diagnostic errors.** Use `None` or empty arrays so that if the attribute is accessed in its uninitialized state, the resulting error (`TypeError: cannot unpack non-iterable NoneType`, `IndexError` on empty array) points directly at the unset state rather than producing another opaque failure.

4. **Add validation at the combination point.** Where parallel inputs are combined, add explicit shape/type checks with informative error messages (e.g., "x and y must have the same shape, got {x.shape} and {y.shape}") so that normalization asymmetries are caught at their origin.

5. **Audit sibling classes and analogous patterns.** If one class in a hierarchy or module has this problem, related classes likely share the same missing-default and asymmetric-normalization patterns. Apply the fix systematically.

### Why This Works

An object should never lack attributes that its own methods expect to exist — `__init__` is the contract for what attributes an instance has. By initializing attributes in the constructor, we decouple the object's structural integrity from the success of any particular processing step. This transforms opaque `AttributeError` cascades into meaningful errors that point at the actual problem (unset state or mismatched inputs). Fixing the normalization asymmetry addresses the root cause, while the defensive defaults ensure that *future* processing failures also produce clear diagnostics rather than half-constructed objects.

## Boundary Cases
- **Subclasses that override `__init__` without calling `super().__init__`:** The defensive defaults won't be set. Ensure all subclass constructors chain properly, or duplicate the defaults.
- **Attributes with non-trivial default construction costs:** If creating a default (e.g., a large empty array) is expensive, use `None` and add explicit null checks in accessor methods with informative error messages.
- **Serialization/pickling:** Ensure that the default values are serializable and that deserialized objects also have all expected attributes, especially if the serialization format predates the fix.
- **Thread safety:** If the setup method can be called concurrently, the window between `__init__` and successful setup completion is a period where the default value is visible to other threads. Ensure downstream code handles the default gracefully.
- **Silent fallback masking real errors:** The default must not be a valid operational value that causes the code to silently proceed with wrong results. `None` is preferred precisely because it will fail loudly when used as real data.

## PR Examples
- matplotlib__matplotlib-23563