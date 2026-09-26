## Problem Description

When data is serialized in one runtime environment (e.g., Python 2) and deserialized in another (e.g., Python 3), runtime-dependent string representations of typed values can introduce formatting artifacts that the consuming environment cannot parse. This pattern manifests when serialization relies on a language's built-in `str()`, `repr()`, or `hex()` conversions rather than a strictly defined, version-stable format specification. The most common example is Python 2's `long` type appending an `'L'` suffix to string and hex representations, which Python 3's `int()` parser rejects outright, causing crashes during deserialization.

This problem is insidious because it is invisible within a single-environment development and testing workflow — the same runtime that serialized the data can always deserialize it. The divergence only surfaces when data crosses environment boundaries: version upgrades, cross-language consumption, or mixed-version distributed systems.

## Root Cause Analysis

The fundamental cause is an **implicit assumption that a language's built-in type-to-string conversion functions produce a universal, stable serialization contract**. They do not. These functions are designed for human-readable display within the current runtime, not for durable interchange. When a serialization layer delegates formatting to `str()` or `hex()` without post-processing, it bakes environment-specific formatting quirks into the persisted data.

Specifically:
- **Python 2** renders `long` integers with a trailing `'L'` in both `str()` and `hex()` output (e.g., `hex(255L)` → `'0xffL'`).
- **Python 3** has no `long` type; `int()` and `int(s, 16)` reject any trailing `'L'` as an invalid literal.
- The serialization format was designed and validated within Python 2, so the `'L'` suffix was never encountered as a problem. Upon migration to Python 3 (or when consuming Python 2-produced artifacts in Python 3), the deserialization path crashes with `ValueError: invalid literal for int() with base 16`.

The root principle: **serialization boundaries must normalize data to a canonical, environment-independent representation**, either at write time or at read time.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ValueError: invalid literal for int()` with unexpected trailing characters (e.g., `'L'`, `'j'`)
  - `crash-exception` during deserialization of data produced by a different runtime version
  - `encoding-corruption` symptoms where parsed values contain unexpected suffixes or prefixes
  - Failures that appear only in cross-version or cross-environment scenarios, never in same-environment round-trip tests
  - Serialized files or streams containing string representations like `'0xffL'`, `'123L'`, or other runtime-decorated numeric literals

### 解决步骤
1. **Audit the serialization layer** to identify every field whose string representation is produced by runtime-dependent conversion functions (`str()`, `repr()`, `hex()`, `oct()`, etc.) rather than by an explicit, controlled format string.
2. **Catalog known formatting divergences** between producer and consumer environments for each identified field. For the Python 2→3 case, this includes: trailing `'L'` on long integers, `'0x'` prefix variations, `repr()` differences for strings (`u''` prefix), and float formatting differences.
3. **Add targeted normalization in the deserialization path** for each affected field. The normalization should strip known environment-specific decorations before parsing. For example:
   ```python
   # Strip trailing 'L' from hex strings before parsing
   value = int(hex_string.rstrip('L'), 16)
   ```
4. **Ensure normalization is idempotent and safe** — when the decoration is absent (i.e., data was produced by the same environment), the normalization must be a no-op. `rstrip('L')` on a string without `'L'` returns the string unchanged.
5. **Add cross-environment round-trip tests** that explicitly serialize using the "foreign" format (e.g., manually append `'L'` to simulate Python 2 output) and verify that deserialization succeeds and produces correct values.

### Why This Works

The fix is placed in the **deserialization path** because that is the only point where you can handle all existing serialized data — including legacy artifacts already persisted — without requiring re-serialization. Targeted, field-level sanitization is preferred over wholesale format migration because:

- It is **minimal**: only the affected fields are touched, reducing risk of unintended side effects.
- It is **backward-compatible**: data produced by the current environment passes through normalization unchanged.
- It is **forward-resilient**: the normalization handles both legacy and current formats transparently.
- It decouples the **logical value** from its **runtime-specific textual representation**, which is the correct abstraction boundary for any serialization layer.

## Boundary Cases

- **Normalization must not be overly aggressive**: stripping `'L'` is safe for integer suffixes, but a generic `rstrip` could corrupt legitimate data if the last character of a valid value happens to match the stripped character (e.g., a hex value ending in `'L'` as a hex digit — though `'L'` is not a valid hex digit, so this specific case is safe; the principle still demands careful scoping).
- **Multiple decorations may coexist**: a value like `'0xFFl'` (lowercase `'l'`) must also be handled; normalization should be case-insensitive where appropriate.
- **Non-numeric fields may also diverge**: string `repr()` differences (e.g., `u'text'` vs `'text'`), boolean representations, and `None`/`null` formatting can vary across environments and require analogous normalization.
- **Bidirectional compatibility**: if the serialization format must be consumed by both old and new environments, ensure that the new environment's serialization output is also parseable by the old one, or version-tag the format.
- **Floating-point formatting differences**: `repr(0.1)` produces different string lengths in Python 2 vs 3; if float fields are serialized as strings, normalization or tolerance-based comparison may be needed.
- **Empty or malformed input**: normalization should gracefully handle empty strings, `None` values, or completely malformed data without masking errors — it should only strip known, expected decorations, not suppress all parse failures.

## PR Examples

- **sympy__sympy-13471**: Python 2's `hex()` output for long integers includes a trailing `'L'` suffix (e.g., `'0xffL'`), which Python 3's `int(s, 16)` rejects. The fix normalizes hex string representations by stripping the `'L'` suffix in the deserialization/parsing path, making cross-version consumption of serialized symbolic expressions robust.