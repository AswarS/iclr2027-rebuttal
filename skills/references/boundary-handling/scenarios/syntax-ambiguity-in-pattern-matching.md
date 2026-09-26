## Problem Description

When a preprocessing or content-insertion step uses a regex or heuristic to detect a specific syntactic construct (e.g., metadata fields, directives, annotations) in order to determine an insertion point or transformation boundary, the pattern may inadvertently match a different, structurally distinct construct that shares the same lexical prefix or surface form. This causes content to be inserted at the wrong position, breaking the structural integrity of surrounding content — for example, separating a heading from its underline, splitting a block in two, or injecting a preamble into the middle of a construct. The bug is typically latent and only surfaces when a specific preprocessing feature (like prolog/preamble injection) is enabled **and** the input begins with the ambiguous syntax in a sensitive position (such as the very first line of a document).

## Root Cause Analysis

Markup languages frequently overload surface-level lexical tokens — colons, brackets, indentation — across syntactically and semantically distinct constructs. A regex designed to recognize one construct (e.g., a reStructuredText field list marker like `:field:`) will silently match another construct that shares the same prefix (e.g., an inline interpreted text role like `:role:`content``). The core cognitive trap is **conflating surface syntax with semantic identity**: the developer observes that two constructs both begin with `:word:` and writes a single loose pattern, failing to account for the full grammar where the same token sequence occupies different syntactic roles.

This is compounded by the fact that the mismatch only manifests under a narrow conjunction of conditions — a specific feature must be active, and the ambiguous syntax must appear at a structurally sensitive location — making the bug easy to miss in typical testing. The underlying principle is that **an approximate pattern is a superset of the intended match set**, and the false positives it admits are invisible until a specific input triggers them.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Content appears at the wrong position after a preprocessing/injection step (wrong-output).
  - A feature that previously worked correctly now breaks specific documents that contain certain markup at the beginning or at structural boundaries (regression-on-edge-case).
  - Structural elements (headings, blocks, lists) are split or corrupted after preamble/prolog injection.
  - The issue only reproduces when a preprocessing feature is enabled **and** the document starts with a construct that superficially resembles the target syntax.

### 解决步骤
1. **Identify the detection pattern**: Locate the regex or heuristic used to detect the syntactic construct (e.g., field list markers) and determine the insertion/transformation logic that depends on it.
2. **Audit the match set**: Test the pattern against all constructs in the language that share the same lexical prefix or surface similarity. Enumerate confusable constructs explicitly (e.g., inline roles `:role:`, cross-references, directives with colons).
3. **Replace with the canonical pattern**: If the upstream parser or language specification already defines a precise pattern for recognizing the construct, reuse it directly. This guarantees definitional consistency — the detection logic matches exactly what the parser itself considers that construct.
4. **Tighten the pattern if no canonical form exists**: If no authoritative pattern is available, refine the regex to require the full syntactic form of the intended construct, not just its prefix. Add anchoring, require trailing structure (e.g., a field body), or exclude known confusable forms.
5. **Guard loop variables**: Initialize any variables (such as line counters or insertion indices) before loops to prevent unbound variable errors when the loop body executes zero iterations (i.e., when no match is found at all).
6. **Add negative regression tests**: Write tests for each confusable construct appearing at the sensitive position to ensure the pattern does not falsely match them.

### Why This Works

Reusing the canonical pattern from the upstream parser guarantees that the detection logic is **coextensive** with the parser's own definition of the construct — no false positives, no false negatives, by construction. This eliminates the category of bugs where an approximation silently admits inputs outside the intended match set. It also future-proofs the logic against parser updates, since the single source of truth is shared. More generally, when you need to recognize a syntactic form, **delegate to the authoritative definition** rather than approximating it with a looser pattern.

## Boundary Cases
- Document begins with an inline role (`:role:`text``) that shares the `:word:` prefix with a field list marker — must not be treated as a field.
- Document begins with a cross-reference or substitution reference that uses colon-delimited syntax.
- Document contains zero lines matching the target construct, causing the detection loop to execute zero iterations — loop variables must still be validly initialized.
- Preamble/prolog injection is disabled — the ambiguous pattern is never evaluated, so the bug remains latent until the feature is toggled on.
- The ambiguous construct appears not at the first line but at other structurally sensitive boundaries (e.g., after a transition or section break).

## PR Examples
- sphinx-doc__sphinx-11445