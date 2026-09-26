## Problem Description

When a generic display or rendering pipeline formats field values for output (e.g., read-only admin views, summary panels, API responses), it typically dispatches on field type to produce an appropriate string representation. For most field types, the programming language's default `str()` or `repr()` conversion produces output that coincides with the domain-correct format. However, certain field types store values whose **canonical serialized form** differs fundamentally from the **language's native stringification** of the equivalent in-memory object. For example, a JSON field stores data as `{"key": "value"}` (double-quoted), but Python's `str()` on the equivalent `dict` produces `{'key': 'value'}` (single-quoted, with potential differences in `True`/`False`/`None` vs `true`/`false`/`null`). When the display pipeline lacks a type-specific branch for such fields and falls through to the generic `str()` path, the rendered output uses the host language's literal syntax instead of the domain-correct serialized format — producing subtly wrong, confusing, or even invalid output.

## Root Cause Analysis

The underlying issue is a **conflation of "printable" with "correctly formatted for the domain."** Generic display pipelines are designed with the implicit assumption that converting a value to a string via the language's default mechanism yields an acceptable external representation. This assumption holds for simple types (strings, numbers, dates) but breaks for field types that act as **bridges between an in-memory representation and a domain-specific serialization format** (JSON, XML, YAML, binary encodings, etc.).

These field types carry an implicit contract: their serialized output must conform to the domain's syntax rules, not the host language's syntax. A `dict` displayed as `{'key': True}` is valid Python but invalid JSON — the correct form is `{"key": true}`. The generic `str()` fallback violates this contract because it was never designed to handle types where the two representations diverge.

A secondary contributing factor is that developers often call the serialization library directly (e.g., `json.dumps()`) rather than delegating to the **field's own serialization method**, which may carry configuration such as custom encoders, sort-key preferences, or indentation settings. This leads to duplicated logic and missed field-level customization.

## Solution Strategy

### 识别信号
- 观测到的现象: Values appear in the UI or output using the host language's native literal syntax rather than the domain-correct serialized format (e.g., single-quoted dict keys instead of double-quoted JSON keys, `True`/`False`/`None` instead of `true`/`false`/`null`).
- Users report that copying displayed values and pasting them into domain-specific contexts (e.g., a JSON validator) produces parse errors.
- The display pipeline has no dedicated branch for the field type in question; it falls through to a generic `str()`/`repr()` conversion.

### 解决步骤
1. **Audit all field types** in the system to identify those whose canonical serialized form differs from the language's default string representation of their in-memory value (e.g., JSON fields, XML fields, YAML fields, binary-encoded fields).
2. **Add a dedicated branch** in the display/formatting dispatcher for each identified field type. This branch should delegate to the **field's own model-level serialization/preparation method** (not the form-level widget method and not a direct call to the serialization library) to produce the correctly formatted string.
3. **Respect field-level configuration** by ensuring the serialization call uses any custom encoder, formatting options, or configuration attached to the field instance, rather than invoking the serialization library with default settings.
4. **Add graceful error handling**: wrap the serialization call in a try/except for type errors, encoding errors, or malformed data, falling back to the generic `str()` display path on failure so that corrupt or unexpected values degrade gracefully rather than crashing the display pipeline.
5. **Add comprehensive tests** covering: normal values, empty containers (`{}`, `[]`), nested/complex structures, `None`/null values, values with special characters, and invalid or corrupt stored values — verifying both correct domain formatting and graceful fallback behavior.

### Why This Works
Delegating to the field's own serialization method restores the **single-responsibility principle**: the field type is the authoritative source for how its values should be externally represented. This ensures that domain-specific syntax rules are honored, field-level configuration (custom encoders, formatting preferences) is respected, and serialization logic is not duplicated across the display layer. The fallback to `str()` on error preserves robustness for edge cases where stored data is malformed.

## Boundary Cases
- **Empty containers** (`{}`, `[]`, `""`) — must serialize to the domain-correct empty representation, not the language's empty literal.
- **`None`/null values** — the field may or may not have a meaningful serialized form for null; the display path must handle this without crashing.
- **Nested structures** with non-primitive types (e.g., `datetime` objects inside a JSON field) — the field's custom encoder must be invoked, not the default serializer.
- **Corrupt or type-mismatched stored values** (e.g., a plain string stored in a JSON field column) — the fallback to generic `str()` must activate cleanly.
- **Boolean and numeric type differences** — `True`/`False` (Python) vs `true`/`false` (JSON), `None` vs `null` — these are the most common and most easily overlooked divergences.
- **Unicode and special character handling** — ensuring the serialization method produces correctly escaped output for the target domain format.

## PR Examples
- django__django-12308