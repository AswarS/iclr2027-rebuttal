## Problem Description

In sequential transformation pipelines where multiple rewrite rules are applied in order to simplify or transform expressions/data structures, an implicit ordering dependency between rules can cause silent failures. Specifically, when a specialized rule is ordered before a more general rule and both compete for overlapping input patterns, the specialized rule may partially transform the intermediate representation in a way that destroys the structural pattern the general rule needs. This bug is particularly insidious because it often manifests only for concrete/literal inputs while appearing to work correctly for symbolic/abstract inputs, since pattern matching behaves differently across input types.

## Root Cause Analysis

The fundamental issue is that sequential pipelines create implicit coupling between transformation rules through the intermediate representation. Each rule mutates the expression before the next rule sees it, meaning rule ordering is not merely a performance concern — it determines correctness.

The deeper principle: two rules that appear to target "different patterns" are **not** order-independent when their pattern domains overlap. A specialized rule may partially match an expression (especially when arguments are concrete/numeric rather than symbolic), apply a partial transformation, and leave behind a structurally altered form that no longer matches the general rule's expected input pattern. The general rule then silently skips the expression, producing an unsimplified or incorrect result.

The cognitive trap is twofold:
1. **Testing bias**: Developers typically test with symbolic inputs, where pattern matchers are more conservative and the specialized rule may not activate. Concrete/literal inputs trigger different code paths in pattern matching, exposing the ordering bug.
2. **Independence assumption**: Rules designed for "different" simplification goals are assumed to be commutative in application order, when in reality they interact through shared intermediate state.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A well-known simplification or transformation works correctly for symbolic/abstract inputs but silently produces unsimplified or wrong results for concrete/numeric inputs.
  - Regression appears after adding or reordering a rule in the pipeline, but only for specific input types.
  - The output is not an error — it is a valid but suboptimal or incorrect expression, making the failure easy to miss.

### 解决步骤
1. **Map overlapping patterns**: Identify all pairs of transformation rules in the pipeline whose input patterns overlap — i.e., both could potentially match the same expression or subexpression. Document what each rule expects as input structure and what it produces as output.
2. **Cross-test rule orderings with diverse input types**: For each pair of overlapping rules, test both orderings (A→B and B→A) with symbolic inputs, concrete/literal inputs, and mixed inputs. Check whether running rule A first destroys the pattern rule B needs, and vice versa. Pay special attention to concrete values, as pattern matchers often behave more aggressively with them.
3. **Reorder: general before specialized**: Place the more general rule (the one handling the broadly expected transformation) before the more specialized rule. The general rule simplifies common cases on the original, unmodified structure; the specialized rule then operates on whatever remains.
4. **Verify no regression on specialized rule**: After reordering, run the specialized rule's dedicated test cases to confirm its expected transformations still apply to inputs that bypass the general rule.
5. **Add concrete-input regression tests**: Write explicit tests using concrete/literal/numeric inputs for the general transformation to guard against future reordering or rule additions that could reintroduce the bug.

### Why This Works

Ordering the general rule first ensures it sees the original, unmodified expression structure — the form most likely to match its broad pattern. The specialized rule, by definition, targets a narrower class of inputs; placing it second means it only acts on expressions the general rule did not fully handle. This respects the principle that **in a sequential pipeline, the rule with the broadest applicability should have first access to the unperturbed input**. The specialized rule's narrower pattern is less likely to be disrupted by the general rule's output because general transformations tend to produce canonical/simplified forms that specialized rules are designed to work with (or ignore).

## Boundary Cases
- **Concrete vs. symbolic divergence**: An expression like `sin(2)*cos(3)` may trigger a specialized product-to-sum rule that `sin(x)*cos(y)` does not, because the pattern matcher evaluates concrete arguments differently. Always test both.
- **Partial activation**: A specialized rule may match and transform only part of a compound expression (e.g., one term in a sum), leaving the rest in a form the general rule cannot recognize. This partial corruption is the hardest variant to detect.
- **Chained dependencies across three or more rules**: Reordering two rules may fix one interaction but introduce a new ordering conflict with a third rule. After any reordering, run the full pipeline test suite, not just tests for the two affected rules.
- **Idempotency masking**: If the pipeline is run multiple times (fixed-point iteration), the bug may self-correct on a second pass, making it invisible in frameworks that iterate to convergence but visible in single-pass pipelines.

## PR Examples
- sympy__sympy-15346