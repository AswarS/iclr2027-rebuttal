## Problem Description

When a class hierarchy uses a composition/delegation pattern — where constructor parameters are forwarded to and stored in a composed sub-object (e.g., an internal dictionary or wrapper) rather than as direct instance attributes — the framework's representation/introspection protocol silently breaks. The `__repr__` method (or equivalent parameter-discovery mechanism) assumes all declared constructor parameters are accessible as same-named attributes on the instance. This assumption fails when parameters physically reside in a delegated storage container, causing `repr()` to either produce the unhelpful default Python object-address string (`<module.ClassName object at 0x...>`) or display `None`/missing values for parameters that do exist but are stored elsewhere.

This pattern is especially insidious in frameworks with rich introspection contracts (e.g., scikit-learn's estimator protocol) where repr, cloning, serialization, and parameter discovery all depend on the same attribute-access convention.

## Root Cause Analysis

The root cause is a **contract mismatch between parameter storage architecture and the framework's introspection protocol**. The protocol defines a uniform contract: every parameter declared in the constructor (or returned by a parameter-discovery method like `get_params`) must be retrievable as a direct instance attribute with the same name. When a class delegates storage to an inner object — perhaps for clean encapsulation or to leverage an existing data structure — this contract is silently violated.

Two compounding factors make this hard to detect:

1. **Missing protocol integration at the base class level**: If the base class in the hierarchy does not inherit from the mixin that provides the standard `__repr__`, none of its subclasses will have a meaningful representation. Python's default `__repr__` still works, so no exception is raised — the failure is purely in output quality.

2. **Invisible indirection**: The parameters *exist* and are *functional* — they're just not where the introspection machinery expects them. Everything works at runtime except for framework features that rely on reflective attribute access (repr, clone, serialization, grid search, etc.).

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `repr()` on instances produces the default `<module.ClassName object at 0x...>` string instead of a human-readable parameter summary.
  - Framework utilities that inspect constructor parameters (cloning, serialization, hyperparameter search) return `None` or raise `AttributeError` for parameters that are clearly set and functional.
  - The base class of the hierarchy does not inherit from the framework's standard mixin/base class that provides `__repr__` or `get_params`.
  - Constructor parameters are forwarded into a sub-object (dictionary, inner config object, etc.) rather than stored as `self.param_name`.

### 解决步骤
1. **Audit protocol participation**: Check whether the base class in the hierarchy inherits from or implements the framework's introspection mixin (e.g., `BaseEstimator` in scikit-learn). If not, add the inheritance at the **lowest common base class** — not at each leaf subclass — to avoid duplication and ensure all future subclasses automatically comply.

2. **Test repr output after adding the mixin**: Call `repr()` on instances and verify that all constructor parameters appear. If some parameters display as `None` or are absent, the repr builder is failing to locate them via direct attribute access, confirming the delegated-storage problem.

3. **Add a fallback lookup in the introspection path**: Extend the repr/parameter-discovery utility to check the delegation container (e.g., an internal dictionary or forwarding object) when direct `getattr` fails or returns a sentinel value. This should be a **minimal, targeted patch** to the resolution path — not a restructuring of the storage architecture.

4. **Validate the full contract surface**: Verify that `repr()`, `get_params()`, `clone()`, and serialization round-trips all produce correct results with actual runtime values matching the constructor signature.

5. **Add regression tests**: Include tests that assert `repr()` output contains expected parameter names and values, and that cloning/serialization preserves all parameters faithfully.

### Why This Works

The fix operates on two levels. First, adding the mixin at the base class ensures the hierarchy *participates* in the protocol at all — this is the prerequisite. Second, adding a fallback lookup in the introspection path **bridges the gap** between the class's internal storage design and the framework's attribute-access contract, without forcing a disruptive refactor of how parameters are stored. This respects the existing delegation architecture while closing the contract gap with minimal risk of side effects. Placing the fix at the base class level follows the DRY principle and guarantees consistency as the hierarchy evolves.

## Boundary Cases
- **Parameters with default values that match the sentinel**: If the fallback lookup uses `None` as a sentinel for "not found," parameters whose legitimate value is `None` may be incorrectly routed to the fallback path. Use a unique sentinel object instead.
- **Subclasses that override `__init__` and store some parameters directly**: The fallback must not shadow direct attributes — always check direct `getattr` first, then fall back to the delegation container.
- **Nested delegation (sub-object delegates to another sub-object)**: The fallback lookup should be shallow and explicit; recursive delegation resolution risks infinite loops or surprising behavior.
- **Multiple inheritance conflicts**: If a subclass already inherits from the mixin through another path, adding it to the base class may change MRO. Verify method resolution order after the change.
- **Third-party subclasses**: External code that subclasses from the hierarchy may rely on the absence of the mixin (e.g., defining its own `__repr__`). The added mixin's method should be overridable without friction.

## PR Examples
- scikit-learn__scikit-learn-14983