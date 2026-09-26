## Problem Description

When a collection of identifiers (such as column names, dictionary keys, or index labels) is stored in a typed container like a numpy array, the container may reinterpret the internal structure of composite identifiers (e.g., tuples, named tuples) rather than treating them as atomic, opaque objects. This causes the identifiers to lose their original identity, leading to lookup failures (KeyError, IndexError) when they are later used to index back into the original data source. The failure typically manifests far from the point of conversion, making it difficult to diagnose.

## Root Cause Analysis

Numpy's array constructor performs type inference and structural interpretation on its elements. When given an iterable of tuples, it treats each tuple as a row of a multi-dimensional array rather than as a single atomic element. For example, `np.array([("a", "b"), ("c", "d")])` produces a 2×2 string array instead of a 1-D array of two tuple objects. This means that extracting an element from the resulting array yields a string (or sub-array), not the original tuple — breaking the round-trip identity contract that downstream lookup code depends on.

The deeper principle is that **opaque identifiers must never be passed through a transformation that inspects or reinterprets their internal structure**. Containers that perform type coercion or dimensional inference (numpy arrays, pandas Series with inferred dtypes, etc.) violate this contract for composite types. Plain Python lists, by contrast, store arbitrary Python objects by reference without any structural interpretation, preserving identity unconditionally.

The cognitive trap is the implicit assumption that identifiers are always simple scalars (strings, integers). This assumption holds in common cases but fails silently when users provide data with hierarchical or multi-level indexing (e.g., MultiIndex column names in pandas), where column names are naturally tuples.

## Solution Strategy

### 识别信号
- 观测到的现象: `KeyError` or lookup failure when indexing into a DataFrame, dictionary, or other mapping using identifiers that were previously stored in a numpy array. The error message may reference a scalar component of a tuple rather than the tuple itself. Crashes may also manifest as shape mismatches or encoding corruption when the array's inferred dimensionality differs from expectations.

### 解决步骤
1. **Audit all conversion points**: Identify every location where collections of opaque identifiers (column names, keys, labels) are converted into numpy arrays via `np.array()`, `np.asarray()`, or similar constructors.
2. **Assess necessity of array semantics**: For each conversion point, determine whether array-specific operations (broadcasting, vectorized math, advanced slicing) are actually performed on the collection. In many cases, the collection is only iterated or indexed by position.
3. **Replace with plain Python lists**: Where no array-specific operations are needed, replace `np.array(identifiers)` with `list(identifiers)`. This preserves every element as-is regardless of its type.
4. **Guard unavoidable array conversions**: If array storage is genuinely required, use `dtype=object` explicitly and verify round-trip identity: convert to array, extract an element, and confirm it can successfully look up the original entry in the source data structure.
5. **Add regression tests with composite identifiers**: Create test cases that use tuple-typed identifiers (e.g., pandas DataFrames with MultiIndex columns) to ensure the full pipeline preserves identifier identity end-to-end.

### Why This Works

Plain Python lists store references to Python objects without any type inference or structural decomposition. A tuple placed into a list remains a tuple when retrieved — its identity is preserved unconditionally. By avoiding numpy's array constructor for collections that serve purely as identifier registries, we eliminate the entire class of coercion-induced identity loss. The fix is minimal, safe, and does not sacrifice performance, since these collections are typically small and are not used for numerical computation.

## Boundary Cases

- **Tuples of mixed types**: A column name like `("group", 1)` may be decomposed differently than `("a", "b")` by numpy, leading to inconsistent dtype inference and even more confusing errors.
- **Single-element tuples**: `np.array([(x,) for x in items])` may collapse the tuple dimension entirely, producing a 1-D array of scalars rather than an array of single-element tuples.
- **Named tuples and dataclass instances**: These are iterable and will be similarly decomposed by numpy's constructor, even though they are semantically atomic identifiers.
- **Nested lists as identifiers**: Lists used as dictionary keys are uncommon (since they're unhashable), but if identifiers are list-like objects, numpy will attempt to create higher-dimensional arrays from them.
- **Empty identifier collections**: `np.array([])` and `list([])` behave differently in downstream shape checks; ensure the replacement handles the empty case.

## PR Examples

- **mwaskom__seaborn-3407**: Seaborn's data transformation pipeline stored column names in a numpy array, which decomposed tuple-typed column names (from pandas MultiIndex columns) into sub-elements, causing `KeyError` when those names were used to index back into the DataFrame. The fix replaced the numpy array with a plain Python list.