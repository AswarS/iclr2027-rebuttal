## Problem Description

When converting runtime type objects to their fully qualified string representations (e.g., `"io.StringIO"` or `"collections.OrderedDict"`), systems that rely on introspection attributes like `__module__` and `__qualname__` may produce incorrect, unresolvable names. This occurs because certain types — particularly C-extension types in the standard library — report metadata that reflects their internal implementation module rather than their public API module. The result is that downstream consumers (documentation generators, serializers, cross-reference resolvers) receive a dotted path that cannot be imported or resolved, leading to broken links, failed lookups, or silent data corruption.

This is a **type-coercion** problem at its core: the system assumes it can coerce a live type object into a canonical string identifier via a uniform introspection protocol, but the protocol's implicit contract is violated by a subset of types whose metadata is populated by their C-level implementation rather than by Python-level conventions.

## Root Cause Analysis

Runtime introspection metadata (`__module__`, `__qualname__`) is populated by each type's implementation, not guaranteed by the language specification. The implicit assumption — that `obj.__module__ + '.' + obj.__qualname__` always yields a publicly importable, canonical path — is an **environment-dependent logic** error. It holds for the vast majority of pure-Python types but breaks for:

1. **C-extension types** that set `__module__` to their internal implementation module (e.g., `_io` instead of `io`, `_collections` instead of `collections`).
2. **Types whose metadata varies across Python runtime versions**, where a bug may be fixed in newer CPython releases but persists in older supported versions.
3. **Third-party extension types** that follow non-standard conventions for `__module__`.

The cognitive trap is **treating runtime-reported metadata as a reliable source of truth**. Developers building reflection or documentation tools naturally assume that standard library objects self-describe correctly. This assumption is never explicitly validated, and the failure mode is subtle — the system produces a plausible-looking but unresolvable string, which only manifests as an error far downstream.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A type's string representation uses an internal/private module path (e.g., `_io.StringIO` instead of `io.StringIO`)
  - Downstream cross-references, hyperlinks, or import resolution fail for specific standard library types
  - The failure is **runtime-version-dependent**: it may appear on Python 3.x but not 3.y
  - The failure is **type-specific**: most types resolve correctly, but a small set of C-extension types do not
  - Regression appears as wrong output for edge-case types that previously worked (or were never tested)

### 解决步骤

1. **Identify the affected type(s):** When a fully qualified name cannot be resolved or produces a broken reference, inspect the type object's `__module__` and `__qualname__` attributes directly. Compare them against the module where the type is publicly documented and importable.

2. **Add a targeted identity-based override:** For each known-broken type, add a special case using an `is` identity check (not string comparison) that maps the type object to its correct fully qualified name. For example:
   ```python
   if obj is io.StringIO:
       return "io.StringIO"
   ```
   This is narrow, safe, and has zero risk of false positives.

3. **Document the workaround explicitly:** Include a comment referencing the specific Python versions affected and, if available, the upstream CPython issue or fix. This ensures the special case can be cleanly removed when the minimum supported runtime version advances past the bug.

4. **Add a regression test:** Write a test that verifies the correct qualified name is produced for each affected type, ensuring the workaround remains effective across CI environments and future refactors.

5. **Consider a general fallback mechanism:** If the pattern recurs for many types, introduce a lookup table (type object → canonical name) that can be maintained centrally, rather than scattering identity checks throughout the codebase.

### Why This Works

An identity-based special case (`is` check) is the safest possible fix because:

- It targets exactly one object in the runtime, with no ambiguity or false positives.
- It does not alter general-purpose introspection logic, limiting blast radius to zero for unaffected types.
- It is trivially removable: once the minimum supported Python version includes the upstream fix, the check and its test can be deleted.
- It makes the implicit assumption explicit — the code now acknowledges that metadata can be wrong and handles it rather than propagating the error silently.

The underlying principle is: **any system that reconstructs canonical identifiers from introspection attributes must have an override mechanism for known-incorrect metadata**, because the metadata contract is implicit, not enforced.

## Boundary Cases

- **Multiple Python versions in CI:** The bug may only manifest on specific CPython versions. Tests must run across all supported versions to catch version-dependent metadata inconsistencies.
- **Types with correct `__qualname__` but wrong `__module__`:** The override must replace the full dotted path, not just one component, since `__module__` and `__qualname__` can be independently incorrect.
- **Subclasses of affected types:** A subclass of a C-extension type may inherit the parent's incorrect `__module__`. The identity check will not match the subclass — this is correct behavior (the subclass has its own identity), but the general introspection path must still handle it gracefully.
- **Third-party C-extension types:** The same pattern can occur outside the standard library. The override table should be extensible or the tool should provide a user-facing configuration for canonical name mappings.
- **Types that are re-exported across modules:** Some types are importable from multiple paths (e.g., `collections.OrderedDict` vs `collections.abc` types). The override should map to the most public, documented path.
- **Removal of workarounds:** When the minimum supported Python version advances, stale overrides become dead code. The documenting comments and associated tests should make cleanup straightforward.

## PR Examples

- **sphinx-doc__sphinx-8627**: Sphinx's type-to-string conversion produced unresolvable references for certain C-extension types (e.g., `struct.Struct`) because their `__module__` pointed to an internal implementation module. The fix added a targeted identity check mapping the type object to its correct public module path, with a comment noting the affected Python versions.