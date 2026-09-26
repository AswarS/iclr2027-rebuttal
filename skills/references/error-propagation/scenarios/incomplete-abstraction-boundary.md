## Problem Description

An abstraction layer (such as an HTTP client library) wraps lower-level I/O operations and translates their exceptions into a library-specific exception hierarchy. However, the exception translation logic is **incomplete**: it handles some categories of errors (e.g., encoding errors, protocol-level errors) but fails to catch transport-layer exceptions (e.g., `socket.error`, OS-level I/O errors) that can occur during **post-initialization I/O** — particularly in streaming, lazy-evaluation, or incremental-read paths. As a result, raw, unwrapped exceptions from layers below the abstraction leak through to callers, violating the library's exception contract and causing unexpected crashes for users who only catch library-level exceptions.

## Root Cause Analysis

The fundamental cause is a **cognitive model mismatch**: developers treat the connection/open phase as the sole point of transport-layer failure, mentally modeling the response or handle object as a stable artifact once it exists. In reality, every subsequent streaming read is an active network operation subject to the same transport-layer failures as the initial connection — socket resets, timeouts, SSL errors, and OS-level I/O errors can all occur mid-stream.

This creates an **incomplete abstraction boundary**. The library's exception translation logic was written with an implicit assumption that only certain categories of errors (data-format, protocol-level) need wrapping at the data-consumption stage, while transport-layer errors were only anticipated at the connection stage. The result is a leaky abstraction: the library's contract promises callers a closed set of exception types, but the actual failure surface is broader than what the translation logic covers.

The pattern is especially insidious because:
- It only manifests under adverse network conditions during data streaming, making it hard to catch in testing.
- The existing exception handlers at the boundary create a false sense of completeness — "we already handle exceptions here."
- The gap is invisible during normal operation and only surfaces as a regression on edge cases.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Users report receiving raw, unwrapped exceptions from layers below the abstraction (e.g., `socket.error`, `urllib3.exceptions.ProtocolError` instead of `requests.exceptions.ConnectionError`).
  - Crash-exception failures occur specifically during **streaming reads** or **lazy iteration** over response data, not during the initial request.
  - Existing `try/except` blocks at the abstraction boundary already catch *some* lower-level exceptions but miss entire categories (typically transport-layer errors).
  - The bug presents as a regression on edge cases — it only triggers when the network connection degrades *after* the response headers have been received.

### 解决步骤
1. **Audit all exception handlers at the abstraction boundary.** Identify every point where the library reads from or writes to the underlying layer — not just the initial connection/open call. Pay special attention to generators, iterators, context managers, and lazy-read paths (e.g., `iter_content`, `iter_lines`, `stream`).

2. **Enumerate all exception types the underlying layer can raise.** Consult documentation and source code for the transport/protocol layer. For network I/O, this typically includes:
   - Socket-level errors (`socket.error`, `socket.timeout`)
   - SSL/TLS errors (`ssl.SSLError`)
   - Protocol-specific errors (e.g., `urllib3.exceptions.ProtocolError`, `urllib3.exceptions.DecodeError`)
   - OS-level I/O errors (`OSError`, `IOError`)

3. **Compare the enumerated set against what is already caught.** Identify the gap — which exception types can the underlying layer raise that are *not* currently translated at this boundary point?

4. **Add catch clauses for the missing exception types** at the same location where other lower-level exceptions are already translated. Map each to the most semantically appropriate library-native exception:
   - Transport/socket failures → library's `ConnectionError`
   - Timeout failures → library's `Timeout`
   - Data decoding failures → library's `ContentDecodingError` or equivalent
   - Avoid mapping everything to a generic catch-all; preserve semantic specificity.

5. **Place the handler at the narrowest possible scope** — the innermost point where raw reads surface into the library layer, co-located with existing exception translation logic. This maintains the established pattern and minimizes over-catching.

6. **Ensure necessary imports are added** for both the lower-level exception types being caught and the library exception types being raised. Verify that the exception chain is preserved (use `raise LibraryError(e) from e` or equivalent) so debugging information is not lost.

7. **Add regression tests** that simulate transport-layer failures during streaming reads and assert that only library-level exceptions propagate to the caller.

### Why This Works

An abstraction layer's exception contract is only as complete as its coverage of **all** failure modes from the layers below. By systematically enumerating the underlying layer's exception surface and ensuring every exception type is caught and translated at every I/O boundary point — not just the initial connection — the abstraction's contract is made whole. Callers who catch only library-level exceptions will correctly handle all failure scenarios, including mid-stream transport failures.

Mapping to the most specific library exception (e.g., `ConnectionError` rather than a generic `RequestException`) preserves semantic information, enabling callers to implement appropriate retry or fallback logic based on the nature of the failure (transient network issue vs. malformed data vs. timeout).

## Boundary Cases

- **Chained generators / nested lazy paths:** If the streaming path involves multiple layers of generators (e.g., a decompression generator wrapping a socket-read generator), each layer may introduce its own exception types. All layers must be audited, not just the outermost.
- **Exception hierarchy changes in dependencies:** A dependency upgrade may introduce new exception types or restructure its hierarchy. The catch clauses must be reviewed when dependencies are updated to ensure continued coverage.
- **Over-catching risk:** Catching too broadly (e.g., bare `except Exception`) at the boundary can mask bugs in the library's own code. Catch only the specific exception types from the underlying layer, not generic base classes.
- **Partial reads before failure:** When a transport error occurs mid-stream, the caller may have already consumed partial data. The library should document whether partial data is retained or discarded, and the exception should ideally indicate that the stream was interrupted, not that it never started.
- **Retry-safe vs. non-retry-safe errors:** Not all transport errors are transient. A `ConnectionResetError` mid-stream may be retryable at the request level, but an SSL certificate error is not. The exception mapping should preserve enough information for callers to distinguish these cases.
- **Context manager cleanup paths:** If the streaming read is inside a `with` block, transport errors during `__exit__` or cleanup may also leak. These paths need the same exception translation treatment.

## PR Examples

- **psf__requests-2148**: The `requests` library's streaming response iteration (`iter_content`) failed to catch `socket.error` exceptions raised by `urllib3` during incremental reads, causing raw socket exceptions to leak through to callers instead of being wrapped in `requests.exceptions.ConnectionError`. The fix added the missing transport-layer exception types to the existing `except` clause in the streaming path.