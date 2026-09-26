## Problem Description

When a class uses weak references as an internal runtime optimization (e.g., to avoid reference cycles or prevent garbage collection interference), and that class is embedded within a larger object graph that users expect to be fully serializable, serialization fails with errors about the inability to serialize weak reference objects. The weak references are an invisible implementation detail — callers have no reason to suspect the parent object cannot be pickled, JSON-serialized, or otherwise persisted. This creates a gap between the runtime memory management contract (internal) and the serialization contract (external) that the containing object implicitly promises.

## Root Cause Analysis

Weak references are a **runtime-only** memory management mechanism. They hold indirect, non-preventing references to objects that may be garbage-collected at any time. This concept has no meaningful representation across a serialization boundary — the serialized form requires concrete object identity and state, not ephemeral indirect pointers.

The fundamental tension is between two orthogonal concerns:

1. **Memory management**: Weak references prevent reference cycles and allow timely garbage collection.
2. **Serializability**: Every component in a serializable object graph must itself be serializable.

Developers introducing weak references typically focus narrowly on concern #1 without verifying that their choice doesn't violate concern #2. When a container class with internal weak references is embedded inside a larger object (e.g., a figure, model, or session) that has an established expectation of being serializable, the container silently breaks that contract. The failure only surfaces at serialization time, often far from the code that introduced the weak references, making it difficult to diagnose.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `PicklingError` at serialization time referencing inability to pickle `weakref` objects
  - The error traceback points into an internal container or grouping class, not user code
  - The weak references were introduced as an optimization invisible to the caller
  - The parent object was previously serializable, or is reasonably expected to be

### 解决步骤
1. **Trace the serialization failure** to identify which classes in the object graph use weak references internally — these are the serialization-breaking components.
2. **Determine the fix location**: prefer fixing at the container level (the class that owns the weak references) rather than at each call site, so all consumers benefit automatically.
3. **Implement custom serialization hooks** (e.g., `__getstate__` / `__setstate__` in Python) on the container class:
   - **`__getstate__`** (serialization): Dereference all weak references to obtain strong (direct) references. Filter out any that have already been garbage-collected. Store the strong references in the serialized state dictionary.
   - **`__setstate__`** (deserialization): Reconstruct the internal weak reference structure from the strong references restored by the deserializer.
4. **Add a round-trip serialization test** that exercises the parent object graph *after* the feature that populates the weak-reference container has been invoked — this ensures the problematic state is present during the test.
5. **Verify runtime semantics are preserved**: After deserialization, confirm that the weak reference behavior is restored and that memory management characteristics (e.g., objects becoming collectible) still hold. The conversion to strong references should exist only transiently in the serialized stream.

### Why This Works

The serialized form is a **snapshot of concrete state**, not a representation of runtime memory management policy. By converting weak references to strong references at serialization time and restoring them at deserialization time, we decouple the two concerns cleanly:

- The **serialized stream** contains only concrete, fully-resolved object references — no dangling or indirect pointers.
- The **live runtime object** retains its weak reference semantics for proper memory management.
- Fixing at the **container level** follows the principle that the component introducing non-serializable state owns the responsibility of bridging the serialization gap. This prevents duplication and ensures all future consumers inherit correct behavior.

## Boundary Cases
- **Already-collected weak references**: At serialization time, some weak references may point to objects that have already been garbage-collected. `__getstate__` must handle `None` dereferences gracefully — either by filtering them out or by storing a sentinel value.
- **Circular reference reconstruction**: If weak references were introduced specifically to break reference cycles, restoring strong references during deserialization could temporarily re-introduce cycles. Ensure `__setstate__` re-wraps in weak references promptly and does not leave strong references lingering.
- **Nested serialization**: If the container is nested inside another container that also customizes `__getstate__`/`__setstate__`, ensure the hooks compose correctly and do not interfere with each other.
- **Subclasses of the container**: Subclasses may add additional weak-reference-bearing state. The base class hooks should be designed to be extensible (e.g., calling `super().__getstate__()`) so subclasses can augment the behavior.
- **Thread safety**: If weak references can be modified concurrently while serialization is in progress, the `__getstate__` implementation may need synchronization to avoid reading inconsistent state.

## PR Examples
- matplotlib__matplotlib-25332