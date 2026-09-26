## Problem Description

When a polymorphic dispatch system (such as a visitor, printer, or serializer) invokes handler methods for different types, it passes optional keyword arguments to convey contextual information about how an object is being used within a larger expression or structure. A new handler method added for a specific type may only implement the "standalone" rendering path, omitting the keyword arguments that the dispatcher passes in compound contexts (e.g., when the object appears as the base of an exponentiation, as a nested operand, etc.). This creates a latent contract violation: the handler works correctly in isolation but crashes with a `TypeError` when the dispatcher passes unexpected keyword arguments during compound expression processing.

This is an instance of **incomplete interface conformance** in a dispatch-based architecture — the new handler satisfies the contract partially but fails to honor the full implicit interface that all sibling handlers implement.

## Root Cause Analysis

Polymorphic dispatch systems define an **implicit interface contract**: every handler method must accept the complete set of keyword arguments that the dispatcher may provide, regardless of whether the handler uses them in all cases. This contract is rarely documented explicitly — it is encoded in the behavior of existing sibling handlers and the dispatcher's calling conventions.

The root cause is **leaf-renderer thinking**: the developer models the new handler as rendering an isolated, self-contained object and tests it only in standalone contexts. They fail to recognize that the dispatcher treats every handler as a participant in a larger composition protocol. The handler is substituted into call sites where the dispatcher passes additional keyword arguments (e.g., `exp=...` to indicate the object is being raised to a power), and because the handler's signature does not accept these arguments, a `TypeError` is raised.

This violates the **Liskov Substitution Principle** — the handler cannot be used interchangeably in all contexts where the dispatcher expects a conforming handler. The bug is particularly insidious because:

1. It only manifests in specific compound expression structures that trigger the extra keyword arguments.
2. The handler passes all simple/standalone tests, giving false confidence in correctness.
3. The implicit contract is not enforced by any type system or abstract base class — it exists only by convention across sibling handlers.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError: unexpected keyword argument` when a specific type appears inside a compound expression (e.g., exponentiation, nested function calls).
  - The handler works correctly when the object is rendered standalone.
  - The crash occurs in the dispatch layer, not in the handler's core logic.
  - Other handlers for similar types in the same dispatcher do not exhibit this failure.

### 解决步骤
1. **Audit the dispatcher's calling conventions**: Examine the dispatch mechanism to identify all keyword arguments it may pass to handler methods. Look at the dispatcher's source code for all call sites where handlers are invoked.
2. **Survey sibling handlers for the full interface contract**: Inspect existing handler methods in the same dispatch family (e.g., other `_print_*` methods in a printer class) to identify the complete set of keyword arguments they accept and how they handle each one.
3. **Update the new handler's signature**: Add all missing keyword arguments to the handler method, with appropriate default values (typically `None` or a sentinel indicating "not in compound context").
4. **Implement compound-context behavior**: When the keyword argument is present, wrap or modify the handler's output following the same pattern used by sibling handlers. For example, if an `exp` keyword indicates exponentiation, wrap the base representation in parentheses and append the exponent notation.
5. **Add comprehensive test cases**: Test the handler both standalone and within every compound expression type that triggers additional keyword arguments from the dispatcher. Include nested compound expressions (e.g., exponentiation of a function that itself contains the target type).

### Why This Works

The fix restores full conformance with the dispatch system's implicit interface contract. By accepting and handling all keyword arguments the dispatcher may pass, the handler becomes a valid substitute in every context — not just the standalone case. This aligns with the Liskov Substitution Principle and matches the established convention across all other handlers in the system. Fixing the individual handler (rather than changing the dispatch mechanism) is the correct approach because the dispatch pattern is a shared convention across potentially hundreds of handlers — modifying the dispatcher would be a high-risk, broad-impact refactor.

## Boundary Cases
- **Multiple keyword arguments in combination**: The dispatcher may pass more than one contextual keyword argument simultaneously (e.g., both `exp` and `parenthesize`). The handler must handle all valid combinations, not just each argument in isolation.
- **Nested compound contexts**: The target type may appear deeply nested (e.g., `(f(x)**2)**3`), causing the dispatcher to invoke the handler with keyword arguments at multiple levels of recursion. The handler must behave correctly regardless of nesting depth.
- **Default/absent keyword arguments**: The handler must produce correct output both when the keyword argument is explicitly passed and when it is absent (the standalone case). Using `None` as a default and branching on its presence is the standard pattern.
- **Subclasses of the target type**: If the dispatch system uses inheritance-based resolution, subclasses of the target type may inherit the handler. Ensure the handler's compound-context logic is valid for all subtypes.
- **New keyword arguments added later**: The implicit contract may evolve over time. Consider using `**kwargs` defensively to absorb future keyword arguments, or establish a project convention for auditing handlers when the dispatcher's interface changes.

## PR Examples
- sympy__sympy-21171