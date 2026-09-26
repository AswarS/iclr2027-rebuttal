## Problem Description

A validation pipeline invokes the same fallible parsing or transformation function at multiple points within a single method or call chain, but only some call sites are wrapped in error handling. The developer implicitly assumes that if an earlier validation step (e.g., a regex match) accepted the input, all subsequent calls to a different parsing mechanism (e.g., a stdlib URL parser) on the same input are guaranteed to succeed. This "validation funnel safety assumption" is false: different validation mechanisms have different grammars and acceptance criteria. The result is that carefully crafted or edge-case inputs pass the initial gate but cause unhandled exceptions at a later, unguarded call site, leaking implementation-level crashes (e.g., `ValueError`) instead of producing clean, domain-appropriate validation errors.

## Root Cause Analysis

The underlying principle is a **mismatch between validation boundaries and assumption boundaries**. Developers mentally model validation as a linear funnel: once input passes an early check, it is considered "clean" for all downstream operations. However, this assumption breaks when:

1. **Different validators have different grammars.** A regex-based pre-check and a stdlib parsing function (e.g., `urlsplit`) do not accept exactly the same set of inputs. An input can satisfy the regex yet cause the parser to raise an exception, or vice versa.
2. **Redundant calls to the same fallible function are not uniformly guarded.** When the same parsing function is called N times across a method, error handling is typically applied at the "obvious" first call site but omitted at subsequent sites under the assumption that "we already validated this."
3. **Successful parsing does not guarantee completeness.** Many parsers return a success result with `None` or empty sub-components (e.g., a URL with no hostname). Code that unconditionally accesses these components (e.g., calling `len(hostname)`) crashes with a `TypeError` or `AttributeError`.

The net effect is **partial error propagation**: some failure modes are caught and converted to domain errors, while others leak as raw implementation exceptions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Unhandled `ValueError`, `TypeError`, or `AttributeError` crashes originating from stdlib parsing functions inside a validation method.
  - The same parsing/transformation function (e.g., `urlsplit`, `int()`, `datetime.strptime`) is called more than once in the same method or call chain.
  - A `try/except` block wraps one call site but not others for the same function.
  - A regex or format check precedes a stdlib parse call, and the developer treats the regex pass as sufficient proof of parseability.
  - Crash inputs are syntactically unusual but not obviously malformed (they pass the regex but trip the parser).

### 解决步骤
1. **Audit all call sites of the fallible function** within the validation method. Create a map: for each invocation, note whether it is wrapped in error handling and what assumptions about prior validation it relies on.
2. **Consolidate to a single early invocation** of the parsing function, wrapped in a `try/except` (or equivalent) that converts low-level exceptions to the domain-appropriate validation error type (e.g., `ValidationError`).
3. **Store and reuse the parse result.** Replace all subsequent calls to the same parsing function with references to the stored result, eliminating redundant invocations entirely.
4. **Add null/None guards on extracted sub-components.** After a successful parse, explicitly check that each sub-component your code depends on (e.g., `hostname`, `port`, `scheme`) is not `None` or empty before performing operations like `len()`, string comparison, or arithmetic on it. Raise a domain validation error if a required component is absent.
5. **Verify that every rejection path raises the domain error type.** Walk through all branches that can reject input and confirm none leak implementation-level exceptions. Add integration tests with edge-case inputs that are designed to pass the regex but stress the parser.

### Why This Works

Consolidating the fallible operation to a single guarded call site eliminates the entire class of "forgot to handle the error at call site K" bugs — there is only one call site to guard. Reusing the stored result removes the implicit assumption that "if it parsed once, it will parse again identically," which can also fail if the input is mutated between calls. Null-guarding sub-components after a successful parse addresses the subtler assumption that "parseable implies complete," converting a potential `TypeError` on `None` into a clean validation error. Together, these steps ensure that the validation method's error-handling contract — "all bad input produces a domain validation error, never a raw crash" — is upheld uniformly.

## Boundary Cases
- **Inputs that are valid under the regex but invalid under the stdlib parser** (e.g., URLs with unusual bracket/colon combinations that a permissive regex accepts but `urlsplit` rejects).
- **Inputs that parse successfully but yield `None` or empty sub-components** (e.g., `///path` parses as a URL with no scheme, no host, and a path — accessing `hostname` returns `None`).
- **Inputs where the parser succeeds but returns semantically nonsensical values** (e.g., port numbers outside the valid range that `int()` converts fine but are not valid ports).
- **Inputs modified between validation steps** (e.g., IDNA encoding of a hostname changes its byte length, causing a length check that passed on the original to fail or vice versa on the encoded form).
- **Locale- or platform-dependent parsing differences** where the same stdlib function behaves slightly differently across environments, causing a parse that succeeds in development to fail in production.

## PR Examples
- django__django-15202