## Problem Description

In multi-branch conditional chains that handle combinations of two optional properties from two operand objects during binary operations, a common regression pattern emerges when guard conditions check the wrong level of nullability. Specifically, after refactoring, a branch intended to handle "operand exists but its attribute is None" instead checks whether the operand container itself is None — a condition already eliminated by earlier branches. This causes the intended fallback logic to be skipped entirely, and execution falls through to a branch that assumes both attributes are present, resulting in a TypeError when a binary function (e.g., `bitwise_or`, addition) receives `None` as an unexpected argument.

This pattern is characteristic of operations on data structures with optional metadata layers (masks, uncertainties, annotations) where two objects are combined and each object may or may not carry a given optional property.

## Root Cause Analysis

The fundamental issue is **conflating container-level nullability with attribute-level nullability** within a progressively narrowing conditional chain.

When a conditional chain is structured so that earlier branches handle the case where an operand container is entirely absent (`operand is None`), the remaining branches are guaranteed that the container exists. A later branch that re-checks `operand is None` — intending to check `operand.attribute is None` — becomes dead code. It can never evaluate to `True`, because that case was already dispatched. The attribute-level None case (container present, attribute absent) is therefore never caught, and execution falls through to the final branch which assumes both attributes are non-None.

The cognitive trap is that developers mentally equate "operand is present" with "operand has all properties populated." This conflation is reinforced when:
- The attribute was historically always present or non-None.
- The None-attribute case is rare in practice and under-tested.
- Refactoring changes variable names or restructures branches, making the distinction less visually obvious.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` when a binary function (e.g., `np.bitwise_or`, `operator.add`) receives `None` as one of its arguments during a combine/merge operation.
  - The error only manifests when one operand **exists** but has a `None`-valued optional attribute (e.g., mask, uncertainty), while the other operand has that attribute populated.
  - The error is a **regression** — it appeared after a refactor of the conditional handling logic, not after a change to the data model.
  - Earlier code paths (both containers None, one container None) work correctly; only the mixed attribute-nullability case fails.

### 解决步骤
1. **Enumerate all state combinations.** For two operands each with an optional attribute, map out the 2×2 (or 3×3 if container-None is separate) matrix: both attributes None, first None only, second None only, both present. Include the container-None cases as a separate dimension if applicable.

2. **Trace the conditional chain branch by branch.** For each branch, annotate which state combinations it handles and which remain for subsequent branches. Verify that no combination falls through unhandled.

3. **Identify the mismatched guard.** Look for a branch where the condition checks `operand is None` (container-level) but the intent is to check `operand.attribute is None` (attribute-level). This is the dead branch — by the time execution reaches it, the container is guaranteed non-None by earlier branches.

4. **Fix the guard condition.** Change the check from container nullability to attribute nullability:
   ```python
   # WRONG: container already guaranteed non-None here
   if operand2 is None:
       return operand1.mask
   
   # CORRECT: check the attribute on the existing container
   if operand2.mask is None:
       return deepcopy(operand1.mask)
   ```

5. **Add comprehensive tests.** Write test cases for every combination in the state matrix, including the previously untested "container present, attribute None" cases for both operands.

### Why This Works

In a chain of conditionals that progressively narrows the remaining state space, each branch's guard must reflect the **remaining** possible states at that point in the chain — not the full original state space. When an earlier branch dispatches all container-None cases, subsequent branches operate in a reduced state space where containers are guaranteed non-None. The only remaining nullability dimension is at the attribute level. Correcting the guard to check `operand.attribute is None` properly partitions this reduced space and ensures every combination is routed to appropriate handling logic.

## Boundary Cases

- **Both operands exist but both have `None` attributes:** Should return `None` (or equivalent identity), not attempt to combine two `None` values.
- **One operand exists with a `None` attribute, the other has a populated attribute:** Should return a copy of the populated attribute, not pass `None` into the binary function.
- **Both operands exist with populated attributes:** Should apply the binary function normally.
- **One operand container is entirely `None` (absent):** Should be handled by an earlier branch and never reach attribute-level checks.
- **Attributes that are falsy but not `None`** (e.g., a zero-valued mask array): Guard must use `is None`, not truthiness checks, to avoid incorrectly treating valid falsy attributes as absent.
- **Deep copy semantics:** When returning a single operand's attribute as the result (because the other is `None`), ensure a deep copy is returned to avoid shared mutable state between the result and the input.

## PR Examples

- **astropy__astropy-14995**: Regression in `NDDataRef` arithmetic where mask handling checked whether the operand object was `None` instead of whether the operand's `.mask` attribute was `None`, causing `TypeError` in `bitwise_or` when combining an object with a mask and an object without one.