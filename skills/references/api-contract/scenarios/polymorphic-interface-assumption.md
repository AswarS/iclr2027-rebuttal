## Problem Description

When a system accepts arbitrary implementations of a polymorphic type (e.g., via configuration, plugin mechanism, or dependency injection), internal utilities may inadvertently rely on an enriched interface provided by the default/built-in implementation rather than the base contract that all implementations are guaranteed to satisfy. This manifests as a crash (typically `TypeError`) when a non-default implementation—one that only fulfills the base contract—is passed in. The offending code assumes all instances support an extended access pattern (e.g., subscript/dict-like access, attribute chaining) that is actually specific to one concrete subclass.

## Root Cause Analysis

The root cause is **familiarity bias with the default implementation**. In polymorphic systems, a base class or interface defines a minimal contract (e.g., a callable method returning a value). The most commonly used subclass often enriches this contract—for example, making the same attribute subscriptable, adding dictionary-like access, or exposing nested properties. Because developers overwhelmingly test with the default implementation, they unconsciously treat the enriched API as universal. The code compiles and passes all tests because the default subclass satisfies both the base and extended contracts.

The deeper principle is a **violation of the Liskov Substitution Principle in reverse**: the consuming code narrows the acceptable type space by depending on subclass-specific behavior, even though the parameter signature and documentation explicitly accept any conforming implementation. This creates a latent defect that only surfaces when a third-party or alternative implementation—one that correctly satisfies the base contract but not the undocumented extended interface—is substituted in.

## Solution Strategy

### 识别信号
- 观测到的现象: `TypeError` such as "object is not subscriptable," `AttributeError` on a method that exists on the default implementation but not on the base class, or similar crashes that only occur when a non-default polymorphic implementation is provided.
- The crash site involves attribute access patterns (subscripting, chaining, indexing) that go beyond what the base class/interface guarantees.
- The entry point explicitly accepts arbitrary subclass instances via a configuration parameter, factory, or registry.

### 解决步骤
1. **Trace the crash to the polymorphic boundary.** Identify the exact attribute access or method call that assumes the extended interface. Confirm that the base class or interface does not guarantee this access pattern.
2. **Audit the base contract.** Determine what the base class actually promises—e.g., a plain callable method, a simple property—versus what the default subclass extends it with (e.g., subscriptable access, rich return types).
3. **Introduce runtime feature detection.** At the point of use, add a type check or duck-typing probe (`isinstance`, `hasattr`, or a try/except) to distinguish objects supporting the extended interface from those that only support the base contract.
4. **Implement a fallback path using an adapter or wrapper.** For implementations that only satisfy the base contract, bridge them to the expected extended interface. Prefer reusing existing adapter classes already present in the codebase over writing new conversion logic. This keeps the primary code path intact for the common case.
5. **Verify behavioral equivalence.** Ensure both the extended and fallback code paths produce the same logical outcome—toggling the same state, setting the same properties, producing the same visual or functional result.
6. **Add regression tests with a non-default implementation.** Create or use a minimal alternative implementation that only satisfies the base contract and exercise the code path that previously crashed.

### Why This Works

The adapter/feature-detection approach respects the **Open/Closed Principle**: the existing code path for the default (enriched) implementation remains untouched, while the new fallback path cleanly handles the general case. By programming against the base contract at the polymorphic boundary and adapting only when needed, the system correctly honors its own promise of accepting arbitrary conforming implementations. The runtime check is a pragmatic acknowledgment that the type system (especially in dynamically typed languages) does not enforce interface conformance at compile time.

## Boundary Cases
- **Partial interface enrichment:** Some alternative implementations may support part of the extended interface but not all of it. Feature detection should be granular enough to handle partial conformance rather than assuming all-or-nothing.
- **Adapter fidelity:** The adapter/wrapper must faithfully replicate the semantics of the extended interface, not just its syntax. For example, if the extended interface returns a mutable view, the adapter should not silently return an immutable copy if downstream code mutates it.
- **Performance-sensitive paths:** If the polymorphic call site is in a hot loop, the cost of repeated `isinstance`/`hasattr` checks may matter. Consider caching the detection result or resolving the code path once at initialization.
- **Future interface evolution:** If the base contract is later enriched to include the previously subclass-specific behavior, the feature detection and adapter code should be revisited to avoid dead code or unnecessary indirection.
- **Multiple non-default implementations:** The fallback path should be generic enough to handle any base-contract-only implementation, not just the one that triggered the original bug report.

## PR Examples
- matplotlib__matplotlib-26020