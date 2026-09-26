## Problem Description

This pattern occurs when a method contains an early-return shortcut based on a **derived numerical property** (e.g., "if the product of scale factors equals 1, return identity") that is placed **before** a type-discriminating check (`isinstance` or equivalent). The shortcut is semantically valid only for a specific subtype of operand, but because it precedes the type guard, it can be triggered by unrelated operand types that happen to produce the same numerical value through entirely different mechanisms. The result is that the operation silently returns a trivial or identity value instead of a meaningful composite result, often manifesting asymmetrically depending on operand order due to dispatch conventions.

## Root Cause Analysis

The underlying issue is **conflating a necessary condition with a sufficient condition**. A derived numerical property (such as a scale factor product equaling 1) is intended to detect a specific semantic situation (e.g., two inverse operands canceling). However, the numerical condition alone is not a unique identifier of that semantic case — other operand types can satisfy the same numerical condition through completely unrelated mechanisms.

The cognitive trap is reasoning that "the only way this numerical value arises is from the intended case," which leads the developer to place the numerical shortcut at the top of the method for performance. This assumption breaks when new operand types are introduced or when existing types interact in unanticipated ways. The type check is the true semantic discriminator; the numerical check is only meaningful **within the context** established by the type check.

This is a specific instance of the broader **implicit assumption violation** pattern: an optimization assumes an invariant that is not enforced by the code structure, and a different code path violates that invariant silently.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss / wrong output**: An operation returns a trivial value (identity, zero, `1`, etc.) instead of a meaningful composite result.
  - **Asymmetric behavior**: `A op B` produces a correct result but `B op A` returns identity (or vice versa), due to one dispatch path hitting the shortcut while the other does not.
  - **Type inconsistency**: The returned value is a bare language primitive (e.g., Python `1`) instead of the framework's symbolic singleton, breaking downstream expression tree operations.

### 解决步骤
1. **Audit early-return shortcuts**: Identify all early-return or fast-path branches in the method that rely on derived/computed numerical properties rather than explicit type checks.
2. **Determine semantic preconditions**: For each shortcut, determine the specific operand type or subtype under which the numerical condition is semantically valid. Ask: "Can any other operand type produce this same numerical value?"
3. **Reorder conditionals**: Move the type-discriminating check (`isinstance` or equivalent) **before** the numerical shortcut. Nest the numerical shortcut inside the type-guarded branch so it only fires when both the type constraint AND the numerical condition are satisfied.
4. **Use framework-appropriate return values**: When returning sentinel values (identity, zero) from symbolic or expression-level methods, return the framework's symbolic singleton (e.g., `S.One`, `S.Zero`) rather than bare language primitives, to maintain type consistency in expression trees.
5. **Test cross-type interactions**: Add test cases covering the cross-type operation that was previously broken, verifying **both operand orderings** produce equivalent and correct results.
6. **Review similar methods**: Check other operator overloads and factory methods in the same class hierarchy for the same pattern — if one method has this bug, siblings likely do too.

### Why This Works

Placing type guards before numerical shortcuts follows the principle of **narrowing the semantic context before applying domain-specific optimizations**. The type check establishes *what kind of operand* we are dealing with; only then does the numerical check become a meaningful discriminator within that context. This ensures fast paths cannot be triggered by operands they were never designed to handle, eliminating an entire class of silent correctness bugs without sacrificing performance for the intended case.

## Boundary Cases
- **Multiple shortcut conditions in the same method**: Each shortcut may require a different type guard; they cannot all share a single `isinstance` check at the top.
- **Subtype hierarchies**: A shortcut valid for a parent type may not be valid for all subtypes, or vice versa. Ensure the type guard is at the correct level of specificity.
- **Commutative vs. non-commutative operations**: Even if the mathematical operation is commutative, dispatch may be asymmetric (`__mul__` vs. `__rmul__`). Both paths must be audited independently.
- **Numerical coincidences across domains**: Values like `0`, `1`, `-1` are especially prone to cross-type collisions because they are common identity/absorbing elements in many algebraic structures.
- **Dynamic type evolution**: If operand types can change at runtime (e.g., through symbolic simplification), a shortcut that was safe at definition time may become unsafe after transformation.

## PR Examples
- sympy__sympy-24909