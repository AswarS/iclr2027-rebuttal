## Problem Description

When a public API exposes structured, multi-component identity information (such as version numbers, dates, or coordinates) solely as an unstructured scalar (typically a string or single number), consumers who need relational comparisons (greater-than, less-than) are forced into ad-hoc parsing. This becomes a correctness hazard when the lexicographic ordering of the string representation diverges from the semantic ordering of the components — for example, `"3.9" > "3.10"` evaluates to `True` under string comparison, but is semantically `False`. The problem pattern is a **type-coercion loss**: rich, structured data is flattened into a lossy scalar representation, and downstream code must reverse-engineer the structure to recover the semantics that were discarded.

## Root Cause Analysis

The underlying cause is **display-sufficiency bias** during initial API design. The developer who first introduces the scalar attribute is typically solving an immediate need — logging, display, or equality checks — and a simple string satisfies that use case. The assumption that "the string is good enough" becomes baked into the interface contract. However, as the API matures, consumers inevitably need relational comparisons, and by that point the unstructured scalar is the only public contract available. This leads to a proliferation of fragile, ad-hoc parsing logic (regex extraction, split-and-cast) scattered across downstream code. The core principle violated is **incomplete abstraction**: the API models only one facet of the data (its display form) while silently discarding another critical facet (its comparable structure). This is a specific instance of the broader anti-pattern where an interface contract fails to expose the full semantic richness of the data it represents.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Downstream code performs `split(".")`, regex extraction, or `int()` casting on a string attribute to compare components.
  - Bug reports where version/date/coordinate comparisons produce wrong results (e.g., `"3.9" > "3.10"` treated as true).
  - Multiple independent consumers re-implement the same parsing logic with slight variations.
  - The string representation contains semantically ordered sub-components (major/minor/micro, year/month/day, pre-release tags) that are collapsed into a single opaque value.

### 解决步骤
1. **Define a structured, comparable data type.** Create a `namedtuple` (or similar immutable, ordered type) whose fields correspond to the semantic components (e.g., `major`, `minor`, `micro`, `releaselevel`, `serial`). Model it after well-known ecosystem precedents (e.g., `sys.version_info`) to minimize consumer surprise and leverage existing mental models.

2. **Implement a parser that maps the string representation to the structured type.** Handle all valid format variants (final releases, pre-releases, dev builds, post-releases). Map variant tags (e.g., `"alpha"`, `"beta"`, `"rc"`) to an ordered enumeration so that Python's native tuple comparison produces correct semantic ordering without any custom `__lt__` logic.

3. **Extract complex resolution logic into a standalone helper.** If the scalar value is itself computed dynamically (from build metadata, environment variables, or VCS tags), factor that computation into a dedicated function. Both the string and structured attributes must share this single source of truth to prevent drift.

4. **Expose both the string and structured representations as top-level attributes.** Compute and cache both on first access to either one, ensuring consistency. Use lazy initialization (e.g., module-level `__getattr__`) if the underlying value is expensive to resolve, so that import-time cost is not increased.

5. **Write ordering-focused tests across boundary cases.** Verify that the structured type's natural comparison semantics match the domain's ordering rules for multi-digit components, pre-release vs. final, dev builds vs. tagged releases, and other edge cases.

### Why This Works

Tuple comparison in Python is **semantically correct by construction** when each component is stored as its proper type: integers for numeric parts and ordered enumerations for categorical levels. Component-wise numeric ordering eliminates the entire class of bugs where lexicographic string comparison diverges from semantic ordering. By co-computing and caching both representations from a single source of truth, the string and structured forms can never drift out of sync — a subtle inconsistency bug that would otherwise be extremely difficult to diagnose. Following ecosystem conventions (e.g., mirroring `sys.version_info`'s shape) makes the structured representation immediately intuitive, reducing the documentation burden and adoption friction.

## Boundary Cases
- **Multi-digit numeric components**: `"3.10"` must sort after `"3.9"`, which only works when components are compared as integers, not as strings or individual characters.
- **Pre-release vs. final ordering**: `"3.10.0a1"` must sort before `"3.10.0"` (final). This requires mapping release-level tags to an ordered enumeration (dev < alpha < beta < candidate < final).
- **Dev builds and post-releases**: `"3.10.0.dev123"` should sort before any pre-release of `3.10.0`, while `"3.10.0.post1"` should sort after the final release. The enumeration must account for these extremes.
- **Missing or optional components**: Some formats omit trailing zero components (e.g., `"3.10"` vs. `"3.10.0"`). The parser must normalize these to a canonical tuple length for consistent comparison.
- **Lazy initialization race conditions**: If the module uses `__getattr__` for lazy computation in a multi-threaded context, ensure that the computation is idempotent or properly synchronized to avoid partial initialization.
- **Backward compatibility**: Existing consumers may rely on the string attribute being a `str` (e.g., for concatenation or formatting). The new structured type must coexist without breaking the string contract.

## PR Examples
- matplotlib__matplotlib-18869