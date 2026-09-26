## Problem Description

When implementing solvers for equations over finite algebraic domains (e.g., modular arithmetic, finite fields, rings), the solver may fail to return complete solution sets because it implicitly assumes all inputs are "generic" (nonzero) elements of the domain. This pattern manifests specifically when:

1. A trivial solution exists at the zero/identity element that satisfies the equation by definition but bypasses the standard algorithmic pathway (e.g., discrete logarithm, residue analysis).
2. The domain is composite and must be decomposed into simpler sub-problems (e.g., via CRT for composite moduli), where the zero-element boundary case must be handled correctly at each level of recursion.
3. Lifting procedures (e.g., Hensel lifting from mod p to mod p^k) degenerate when the derivative or lifting formula encounters the zero element or when the characteristic divides the exponent.

The result is a **partial result** — the solver returns some valid solutions but silently omits the trivial/boundary ones.

## Root Cause Analysis

The underlying principle is **implicit domain restriction through algorithmic assumption**. Algebraic solvers are designed around the "generic" case where elements have well-defined multiplicative inverses, participate in residue classes, and engage discrete logarithm or index calculus machinery. The zero element is structurally different: it trivially satisfies power equations (0^n ≡ 0) but does not participate in multiplicative group operations.

The cognitive trap is that developers mentally model the solution space as consisting only of elements that engage the sophisticated algebraic machinery. The domain technically includes boundary elements (zero, identity, nilpotent elements) that satisfy the equation through a completely different — and trivially verifiable — mechanism. This is a form of **boundary-blindness** where the algorithm's preconditions silently exclude valid solutions rather than explicitly handling them.

In composite domain decomposition, this error compounds: if the zero-check is missing in the base (prime) case, every recursive decomposition path that reaches that base case will also miss the trivial solution, leading to systematically incomplete results across all composite moduli.

## Solution Strategy

### 识别信号
- 观测到的现象: **partial-result** / **wrong-output** — the solver returns a subset of correct solutions but omits solutions at domain boundary elements (especially zero)
- The solver works correctly for "generic" inputs but fails when the solution involves the zero/identity element
- Composite modulus cases miss solutions that should appear via CRT reconstruction because a sub-problem's solution set is incomplete

### 解决步骤
1. **Enumerate degenerate inputs explicitly**: Before entering the main algorithmic pathway, check whether the zero element (or any other boundary/identity element) of the domain satisfies the equation. If so, include it in the result set unconditionally.
2. **Place the boundary check at the correct architectural layer**: In a solver that dispatches between composite and simple (prime/irreducible) domain cases, place the zero-element check in the **simple case handler** — after the composite dispatch but before the main residue/feasibility analysis. The composite case will naturally invoke the simple case recursively, so the check runs exactly once per prime sub-problem without interfering with decomposition logic.
3. **Handle degenerate cases in lifting/extension steps**: When extending solutions from a sub-domain to a larger domain (e.g., Hensel lifting from mod p to mod p^k), detect when the derivative or lifting formula degenerates (e.g., division by zero in Newton iteration). Fall back to brute-force enumeration over the finite set of possible lifts at each level — this is both correct and efficient given the small size of the lift space.
4. **Combine sub-domain solutions exhaustively**: When decomposing a composite domain into coprime components, solve each component independently, then combine **all** solutions via the appropriate reconstruction theorem (e.g., CRT) applied to the full Cartesian product of per-component solution sets.
5. **Write targeted boundary tests**: Include test cases where the input is congruent to the zero element, ensuring the trivial solution appears in the output. Test both prime and composite moduli.

### Why This Works

The zero element satisfies power equations through a fundamentally different mechanism than nonzero elements — it is an absorbing element under multiplication. By checking for it explicitly before entering the main algorithm, we decouple the trivial-solution logic from the generic-case logic. Placing this check in the prime base case ensures correctness propagates upward through both lifting (p → p^k) and decomposition (composite → prime components via CRT) without duplication or interference. The brute-force fallback during lifting is safe because the lift space at each level is bounded by p, which is small.

## Boundary Cases
- Zero element as a solution to x^n ≡ 0 (mod m) for any n ≥ 1
- Nilpotent elements in composite rings (e.g., x ≡ 0 mod p but x ≢ 0 mod p^k)
- Cases where the exponent is divisible by the characteristic (p | n), causing the lifting derivative to vanish
- Identity element (x = 1) when it trivially satisfies the equation but is excluded by logarithm-based methods
- Composite moduli where only some prime-power components have zero solutions, requiring correct CRT combination with non-trivial solutions from other components

## PR Examples
- sympy__sympy-18199