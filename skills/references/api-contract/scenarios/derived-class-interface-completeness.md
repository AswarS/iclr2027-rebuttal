## Problem Description

When a class hierarchy uses inheritance to share implementation, derived classes may manually define their constructor signatures rather than systematically mirroring the base class's full parameter set. This creates an **interface completeness gap**: the base class (and possibly sibling derived classes) support parameters that the omitting derived class does not accept, even though the inherited machinery fully supports them. Users who rely on documentation, the base class contract, or experience with sibling classes encounter a `TypeError` ("unexpected keyword argument") when they attempt to use a parameter that should logically be available.

This is a specific instance of the **incomplete abstraction** pattern — the derived class breaks the substitutability contract by selectively curating which base-class parameters it exposes, rather than treating the base class's interface as the canonical specification.

## Root Cause Analysis

The underlying cause is **selective inheritance by manual curation**. When developers create derived classes, they mentally categorize each base-class parameter as "relevant" or "irrelevant" to the specific variant they are building. Parameters that feel like they belong to a sibling class's concern — or that seem orthogonal to the derived class's distinguishing feature — get silently dropped from the constructor signature.

This reasoning breaks down because cross-cutting concerns (e.g., caching intermediate results, controlling verbosity, setting tolerances) are **orthogonal to the axis that distinguishes sibling classes**. They belong to the shared abstraction, not to any single variant. The result is a symmetry break: two classes that should be interchangeable from the caller's perspective diverge in their accepted parameters, violating the Liskov Substitution Principle at the interface level.

The problem is compounded when documentation is generated against the base class's capabilities or when users learn the API through one sibling and then switch to another, creating a reasonable expectation that the full parameter set is universally supported.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError: __init__() got an unexpected keyword argument '<param>'` when passing a parameter that the base class or a sibling class accepts.
  - Documentation (auto-generated or manually written) references a parameter that the derived class's constructor does not include.
  - Code review reveals that a derived class's `super().__init__(...)` call could forward a parameter but the derived class never accepts it.
  - Sibling classes derived from the same base have asymmetric constructor signatures without a clear semantic justification.

### 解决步骤
1. **Audit the base class constructor's full parameter list.** For each parameter, determine whether it controls cross-cutting behavior (shared implementation) or variant-specific behavior.
2. **Compare every derived class's constructor signature against the base.** Flag any parameter present in the base (or in a sibling) that is missing from a derived class, especially if the inherited methods that consume that parameter are not overridden.
3. **For each missing parameter, evaluate the omission.** The default assumption should be that the parameter belongs in the derived class unless there is a clear, documented semantic reason to exclude it (e.g., the parameter is meaningless for that variant's algorithm).
4. **Add the missing parameter to the derived class's constructor.** Set its default value to match the base class default. Forward it in the `super().__init__(...)` call so the shared implementation receives it.
5. **Update the derived class's docstring.** Document the parameter, adjusting type constraints or shape descriptions to reflect any variant-specific nuances.
6. **Add or extend tests** to verify that the parameter is accepted and has the expected effect in the derived class.

### Why This Works

Treating the base class parameter set as the **canonical interface specification** — and requiring explicit justification for omission rather than explicit justification for inclusion — ensures that all derived classes honor the substitutability contract. Cross-cutting parameters flow naturally to every variant, and users can rely on a uniform API across the hierarchy. This eliminates the cognitive trap of hand-picking parameters per variant and prevents the symmetry breaks that cause runtime `TypeError` failures.

## Boundary Cases
- **Parameter is genuinely meaningless for a variant.** If a derived class's algorithm makes a base-class parameter semantically void (e.g., a solver-specific tolerance for a solver that doesn't iterate), the parameter should still be accepted for interface compatibility but may be documented as ignored, or a warning may be emitted.
- **Parameter interacts differently across variants.** The parameter may be valid but have subtly different semantics (e.g., different default values, different valid ranges). The derived class should still accept it but must document the divergence.
- **New parameters added to the base class after initial release.** Every addition to the base class constructor must trigger a sweep of all derived classes — CI checks or linting rules that compare signatures can automate this.
- **Multiple inheritance or mixin chains.** When a class inherits from multiple bases, the union of all bases' parameters should be considered, with conflict resolution documented explicitly.

## PR Examples
- scikit-learn__scikit-learn-10297