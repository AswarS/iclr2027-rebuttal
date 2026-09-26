## Problem Description

When a system implements a multi-stage decoding or deserialization pipeline with fallback paths (e.g., primary decoder → legacy decoder), the fallback chain can fail catastrophically if the input data conforms to **neither** the primary nor the legacy format. This pattern emerges when developers implicitly assume the input space is fully partitioned between "modern format" and "legacy format," neglecting a third category: data that is corrupted, truncated, from an incompatible source, or from a version so old it predates all known formats. The last fallback in the chain raises an unhandled exception, which propagates up and crashes the application — often in a loop if the corrupted input is persistently presented (e.g., a stale cookie on every request).

## Root Cause Analysis

The root cause is an **unhandled propagation gap at the tail of a fallback chain**, driven by two reinforcing cognitive errors:

1. **Partition Assumption Violation**: Developers mentally model the input domain as a union of two (or more) known formats and design each fallback to handle one partition. They fail to account for inputs outside all known partitions — the "none of the above" category. This third category is small in normal operation but becomes significant during upgrades, migrations, data corruption, or adversarial input.

2. **Partial Function Masquerading as Total Function**: The fallback decoder is treated as if it can handle any input that the primary decoder rejects. In reality, the fallback is itself a partial function — it can only decode inputs that conform to the legacy format. When given arbitrary bytes, it raises its own exception (e.g., `UnicodeDecodeError`, `binascii.Error`, `ValueError`), which no handler catches because the developer assumed the fallback would always succeed on non-primary inputs.

The combined effect is that the error recovery chain lacks a terminal safe-default stage. The chain is modeled as `try primary → try fallback` when it should be `try primary → try fallback → return safe default`. The missing terminal stage is the propagation gap.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Application crashes with an **unhandled exception originating from the fallback decoder**, not the primary decoder.
  - The exception type is typically a low-level data format error (`UnicodeDecodeError`, `binascii.Error`, `zlib.error`, `ValueError`, `struct.error`) rather than a domain-level error.
  - The crash is triggered by stale or corrupted client-side tokens (cookies, cached blobs, session identifiers) presented after an upgrade or migration.
  - The crash may repeat in a loop because the corrupted input is re-sent on every request (e.g., a browser cookie), creating a denial-of-service condition for affected users.
  - The primary decoder fails with an expected, handled error (e.g., signature mismatch), and execution enters the fallback path, which then fails unexpectedly.

### 解决步骤
1. **Map the full decode/fallback chain**: Enumerate every stage from initial input to final deserialized output. For each stage, catalog the complete set of exceptions it can raise — not just the ones you expect.
2. **Classify each stage as total or partial**: A stage is *total* only if it provably handles all possible byte sequences without raising. Assume every stage is *partial* unless you can prove otherwise. Pay special attention to the **last** fallback stage — this is where the gap almost always exists.
3. **Wrap each fallback stage in its own exception handler**: Catch a broad exception set (or use a base `Exception` catch) around each fallback. When both the primary and all fallback paths fail on the same input, the data is irrecoverable — do not attempt further decoding.
4. **Terminate the chain with a safe default**: After all stages are exhausted, return a well-defined safe default value (e.g., an empty dictionary, a fresh session, a null object). This value should effectively reset the client's state so that subsequent requests proceed normally.
5. **Log the failure for diagnostics and security**: Emit a warning or security log entry containing the exception details and (sanitized) input metadata. This gives administrators visibility into corrupted or potentially tampered data without sacrificing application availability.
6. **Verify the safe default breaks the crash loop**: Ensure that returning the safe default causes the system to overwrite or invalidate the corrupted input (e.g., set a new session cookie), so the client does not re-present the same bad data on the next request.

### Why This Works

A fallback chain is structurally analogous to a chain of `try/except` blocks. The fundamental invariant is: **the chain must always terminate with a value, never with an unhandled exception**. By adding a terminal safe-default stage, the chain becomes a total function over the input domain — it maps every possible input (valid modern, valid legacy, or garbage) to a defined output. This preserves availability: a user with a corrupted token is silently reset to a clean state rather than trapped in a crash loop. The logged warning preserves observability, so the silent recovery does not mask systemic issues like data corruption or active tampering.

## Boundary Cases

- **Input that is valid in one format but decodes to semantically wrong data in another**: The fallback may "succeed" (no exception) but produce garbage state. Consider adding integrity checks (checksums, expected structure validation) after each decode stage, not just exception handling.
- **Empty or zero-length input**: Some decoders accept empty input and return empty output; others raise. Ensure the chain handles the empty-input case explicitly if it has distinct semantics (e.g., "no session" vs. "corrupted session").
- **Extremely old legacy formats**: If the system has gone through multiple format generations, the fallback chain may need more than two stages. Each additional stage must follow the same partial-function wrapping discipline.
- **Concurrent upgrade/rollback scenarios**: During rolling deployments, one server may write a new-format token that another server (still on the old version) cannot read. The fallback chain on the old server must also terminate safely, not just the new server's chain.
- **Adversarial input**: An attacker may deliberately craft input designed to pass the primary decoder's signature check but crash the fallback. The broad exception handling at each stage mitigates this, but consider rate-limiting or flagging repeated decode failures from the same client.
- **Silent state reset masking bugs**: If the safe default is returned too eagerly (e.g., on transient errors unrelated to format), users may experience unexpected logouts. Restrict the safe-default path to exceptions that genuinely indicate undecodable input, not infrastructure failures like database timeouts.

## PR Examples

- **django__django-13321**: Django's session decoding pipeline used a primary decoder (modern signed-cookie format) with a fallback to a legacy format. When a cookie was corrupted or from an incompatible source, the primary decoder raised a handled `BadSignature` error, but the legacy fallback then raised an unhandled `binascii.Error` or similar low-level exception. The fix wrapped the fallback path in its own exception handler and returned an empty session dictionary (safe default) when all decode paths failed, breaking the crash loop for users with stale cookies after an upgrade.