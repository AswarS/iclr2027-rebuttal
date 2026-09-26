## Problem Description

When a framework auto-generates methods on a class based on per-class configuration (e.g., generating display resolvers from field choices, creating label accessors from attribute metadata), the generation logic may use a broad existence check like `hasattr(cls, method_name)` to avoid overwriting existing methods. Because `hasattr` traverses the full Method Resolution Order (MRO), it finds inherited auto-generated methods from parent classes and silently skips regeneration on the child class — even when the child has redefined the configuration that the method depends on. This leaves a stale parent-version method in place, producing incorrect results when the child's configuration diverges from the parent's.

This is a **leaky abstraction** problem: the inheritance-aware lookup conflates "a method was explicitly defined on this class" with "a method is reachable somewhere in the ancestor chain," violating the implicit contract that auto-generated behavior should reflect the current class's own configuration.

## Root Cause Analysis

The root cause is a **scope mismatch** between the guard condition and the configuration it protects. Auto-generated methods are coupled to per-class configuration (e.g., a `choices` list on a specific model field). When a child class overrides that configuration, the dependent method must be regenerated for that child. However, the guard condition (`hasattr(cls, name)`) operates at the inheritance-chain level, not the class-dict level. It sees the parent's auto-generated method as "already present" and skips regeneration, even though the parent's method encodes the parent's configuration — not the child's.

The underlying principle: **whenever generated artifacts depend on per-class state, the existence check that gates regeneration must be scoped to the exact class (`cls.__dict__`), not the full inheritance hierarchy (`hasattr` / `getattr` with MRO traversal).** Failing to do so creates an implicit assumption that inherited methods remain valid across configuration changes at different inheritance levels — an assumption that breaks as soon as a subclass diverges.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: A child class's auto-generated method returns values based on the parent's configuration rather than its own (e.g., calling `get_FOO_display()` on a child model returns `None` or a parent-specific label for a value that only exists in the child's choices).
  - **Regression on edge case**: The behavior is correct when no inheritance is involved, but breaks specifically when a subclass redefines the driving configuration (extended choices, modified metadata, etc.).
  - **Silent failure**: No error is raised — the stale inherited method simply produces incorrect results.

### 解决步骤
1. **Locate the guard condition** in the registration/contribution logic that decides whether to generate or skip the auto-generated method. Look for patterns like `if hasattr(cls, method_name)` or `if getattr(cls, method_name, None) is not None` in field registration, metaclass setup, or descriptor `contribute_to_class` methods.
2. **Verify the scope of the check**: Confirm that the existing check traverses the MRO (e.g., `hasattr` does) rather than inspecting only the current class's own namespace (`cls.__dict__`).
3. **Replace with a class-dict-only check**: Change the guard to `if method_name in cls.__dict__` (or equivalent). This ensures that only methods explicitly defined on the current class — whether by the developer or by a prior registration on this exact class — block regeneration.
4. **Preserve user-defined method protection**: Ensure that if a developer has explicitly written a method with the same name directly on the class (present in `cls.__dict__` and not auto-generated), it is still respected and not overwritten.
5. **Add targeted regression tests**: Write tests where a child class overrides the configuration (e.g., extends or replaces a choices list) and verify that the auto-generated method on the child returns results consistent with the child's configuration, including values that exist only in the child's version.

### Why This Works

`cls.__dict__` contains only attributes defined directly on `cls`, excluding anything inherited. By scoping the existence check to `cls.__dict__`, the guard correctly distinguishes between:
- **Inherited auto-generated methods** (from a parent) → not in `cls.__dict__` → regeneration proceeds, producing a method tied to the child's configuration.
- **User-defined methods on this class** → in `cls.__dict__` → regeneration is skipped, respecting the developer's explicit override.

This aligns the scope of the guard with the scope of the configuration it depends on: both are per-class, so the check must also be per-class.

## Boundary Cases
- **Multi-level inheritance**: A grandchild class that does *not* redefine the configuration should still correctly inherit the auto-generated method from whichever ancestor last regenerated it. The fix must not force unnecessary regeneration when configuration hasn't changed.
- **Diamond inheritance / multiple inheritance**: When multiple parents contribute auto-generated methods for the same attribute, the class-dict check must still behave correctly — only blocking regeneration if the current class itself already has the method.
- **User-defined override on a child class**: If a developer explicitly defines the method on a child class (e.g., a custom `get_status_display`), the class-dict check will find it and correctly skip auto-generation, preserving the developer's intent.
- **Abstract base classes**: If an abstract parent defines configuration and auto-generates a method, concrete children that redefine the configuration must still get fresh auto-generated methods.
- **Dynamic class modification**: If configuration is changed after class creation (e.g., monkey-patching choices), the auto-generated method will not automatically update unless the registration logic is re-invoked — this is a separate concern from the inheritance scoping fix.

## PR Examples
- django__django-12284