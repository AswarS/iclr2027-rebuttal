## Problem Description

When converting byte-string values to native string types using a language's generic string constructor (e.g., `str()` in Python 3), the constructor produces the **debug representation** of the bytes object rather than the **decoded semantic content**. For example, `str(b'GET')` yields the literal string `"b'GET'"` instead of `"GET"`. This pattern is especially insidious in cross-version codebases (Python 2/3) where the distinction between `bytes` and `str` did not exist in the original environment, causing the code to appear correct under one runtime but silently corrupt data under another.

The corruption propagates downstream — HTTP methods become unrecognized, headers are malformed, protocol negotiations fail — producing symptoms (e.g., 404 responses, encoding errors) that are far removed from the actual coercion site, making diagnosis difficult.

## Root Cause Analysis

The underlying principle is **environment-dependent mental model validation**. In Python 2, `str` and `bytes` are aliases for the same type, so `str(b'GET')` trivially returns `'GET'`. Developers internalize a mental model that `str()` universally extracts content from any string-like input. This model is valid in one environment but silently invalid in another.

In Python 3, `bytes` and `str` are distinct types. When `str()` receives a `bytes` object without an explicit encoding argument, it falls back to calling `bytes.__repr__()`, which produces the debug representation (e.g., `"b'GET'"`). This is **representation rendering**, not **content extraction**. The semantic gap between these two operations is the root cause.

The problem is amplified at library boundaries where upstream callers, compatibility shims, or middleware may pass byte strings where native strings are expected. Without defensive type-aware conversion, the library silently accepts and propagates corrupted values.

## Solution Strategy

### 识别信号
- 观测到的现象: Values like `b'GET'` appear as the literal string `"b'GET'"` in logs, network traces, or error messages. Downstream failures include unexpected 404 responses, protocol errors, encoding corruption, or assertion failures on string comparisons. The code uses `str()` on values that may be byte strings, and the bug manifests only under Python 3 (or equivalent environments where bytes ≠ str).

### 解决步骤
1. **Audit all coercion sites**: Search the codebase for all locations where a generic string constructor (`str()`) is applied to values that could be byte strings — particularly at API boundaries, request/response processing, and anywhere external input is normalized.
2. **Replace with encoding-aware conversion**: Substitute `str(value)` with an explicit decode path. If the value is `bytes`, call `value.decode('utf-8')` (or the appropriate encoding). If the value is already a native `str`, return it unchanged.
3. **Centralize in a utility function**: Create or use an existing utility (e.g., `to_native_string(value, encoding='ascii')`) that encapsulates the type-check-and-branch logic. This prevents the same mistake from recurring across the codebase and localizes the cross-version compatibility concern.
4. **Guard library boundaries defensively**: At every public API entry point where string-typed parameters are accepted, apply the utility function so that byte-string inputs from callers are handled gracefully rather than silently corrupted.
5. **Add regression tests**: Write test cases that explicitly pass byte-string inputs (e.g., `b'GET'`, `b'Content-Type'`) and assert that the converted output equals the decoded semantic content (`'GET'`, `'Content-Type'`), not the representation.

### Why This Works

The fix replaces an **implicit, type-unaware** coercion (`str()`) with an **explicit, type-aware** conversion that branches on the input type. For `bytes`, it performs content extraction via `.decode()`, which interprets the byte sequence according to a specified encoding. For `str`, it passes through unchanged. This ensures the operation's semantics are always "extract the textual content," regardless of the input type or runtime environment. Centralizing this logic in a utility function enforces consistency and prevents regression.

## Boundary Cases
- **Non-ASCII byte strings**: When byte strings contain non-ASCII data, the chosen encoding (e.g., `'ascii'` vs `'utf-8'` vs `'latin-1'`) must match the actual encoding of the data; using `'ascii'` with non-ASCII bytes will raise a `UnicodeDecodeError` unless an error handler is specified.
- **Values that are neither `str` nor `bytes`**: Numeric types, `None`, or custom objects passed to the utility function — decide whether to fall back to `str()` for these or raise a `TypeError`.
- **Already-correct Python 2 codepaths**: In dual-version codebases, ensure the utility is a no-op under Python 2 where `str` and `bytes` are identical, to avoid introducing unnecessary decode calls.
- **Encoding mismatch at boundaries**: Upstream callers may encode strings in an encoding different from what the utility assumes; the utility should either accept an encoding parameter or document its assumption clearly.
- **Empty byte strings**: `str(b'')` produces `"b''"` in Python 3, which is a two-character corruption rather than an empty string — the same pattern applies even to trivial inputs.

## PR Examples
- **psf__requests-2317**: The `requests` library used `str()` to normalize HTTP method values, which corrupted byte-string methods like `b'GET'` into `"b'GET'"` under Python 3, causing downstream 404 errors. The fix replaced the generic constructor with an encoding-aware native string conversion utility.