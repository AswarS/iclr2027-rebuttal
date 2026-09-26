## Problem Description

In data transformation pipelines that apply multiple sequential steps (e.g., lowercasing → character replacement → regex consolidation → stripping), boundary cleanup operations (trimming unwanted leading/trailing characters) are often placed at an intermediate stage rather than as the final step. This creates a subtle ordering dependency: later pipeline stages can introduce or re-expose non-content characters at the boundaries that the earlier cleanup step never anticipated. The result is output that violates the expected "clean edges" invariant — for example, a slug that begins or ends with dashes because a consolidation step converted whitespace to dashes *after* the strip step had already run.

This pattern is especially insidious because it only manifests with adversarial or edge-case inputs (leading/trailing whitespace, special characters, mixed separators) and passes silently for "normal" inputs where no boundary noise survives the pipeline.

## Root Cause Analysis

The fundamental issue is a **misplaced invariant enforcement**. Boundary cleanup is an invariant about the *final output shape*, not about any intermediate representation. When it is positioned before later transformation stages, those stages can violate the invariant without any subsequent enforcement to catch the regression.

Two cognitive traps drive this mistake:

1. **Isolated step reasoning**: Developers mentally model each pipeline step in isolation and fail to reason about how a later step (e.g., replacing spaces with dashes) can reintroduce the exact class of problem an earlier step (e.g., stripping whitespace) was meant to solve.
2. **Incomplete character-class scoping**: Boundary cleanup is treated as a whitespace-only concern scoped to the raw input, rather than as a post-processing concern about *all* non-content characters (dashes, underscores, dots, etc.) that any pipeline stage might leave at the edges.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Output strings contain unexpected leading or trailing separator characters (e.g., dashes, underscores) despite a strip/trim step existing in the pipeline.
  - Edge-case inputs with leading/trailing whitespace or special characters produce malformed output, while "clean" inputs work correctly — a classic **regression-on-edge-case** / **wrong-output** signal.
  - The strip step targets only whitespace, but the pipeline also produces dashes, underscores, or other non-content characters via substitution or consolidation stages.

### 解决步骤
1. **Trace the full pipeline end-to-end with adversarial inputs.** Construct inputs with leading/trailing whitespace, separators, special characters, and mixed combinations. Log the output of every stage to see exactly what survives and what gets introduced at each step.
2. **Catalog the complete boundary character set.** Identify every character class that could appear at the edges of the output after *all* transformation stages complete — not just what exists at the input stage. Include characters introduced by substitution (e.g., dashes from space-to-dash replacement) and characters preserved by filtering (e.g., underscores allowed through a character whitelist).
3. **Relocate boundary cleanup to the very last step of the pipeline.** Move the strip/trim operation after all substitutions, regex consolidations, and filtering are complete. This ensures the cleanup enforces the final-shape invariant with full knowledge of what the pipeline has produced.
4. **Extend the strip character set to cover all non-content characters.** Update the strip call to remove not just whitespace but also dashes, underscores, and any other separator characters the pipeline can produce or preserve. For example, change `.strip()` to `.strip('-_ \t\n')` or equivalent.
5. **Document the ordering guarantee and character set.** Update docstrings or inline comments to explicitly state that boundary cleanup is the final step and to enumerate the full set of stripped characters, so future maintainers do not inadvertently reorder or narrow the cleanup.

### Why This Works

A final-shape invariant can only be reliably enforced at the *end* of the pipeline, after all transformations that could violate it have completed. By placing boundary cleanup last and broadening its character set to encompass every non-content character the pipeline can produce, the solution eliminates the ordering dependency entirely. No matter what intermediate stages do, the final strip guarantees clean edges. This transforms a fragile, position-dependent correctness property into a robust, position-independent one.

## Boundary Cases
- Inputs consisting entirely of whitespace or separator characters (should produce an empty string, not a string of dashes).
- Inputs with mixed leading/trailing characters (e.g., `"  --hello-- "`) where both whitespace and dashes must be stripped.
- Unicode whitespace or non-ASCII separator characters that may not be covered by a simple ASCII strip call.
- Inputs where consolidation produces runs of separators at the boundaries (e.g., `"   hello   "` → `"---hello---"` before final strip).
- Pipelines with configurable or pluggable stages where the set of possible non-content characters varies by configuration.

## PR Examples
- django__django-12983