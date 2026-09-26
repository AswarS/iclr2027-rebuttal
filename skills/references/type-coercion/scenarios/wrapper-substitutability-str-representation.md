## Problem Description

When a wrapper type (e.g., a Python `Enum`) inherits from both a primitive type (`str`, `int`) and a base class that provides its own `__str__` method, the Method Resolution Order (MRO) can cause `str()` to return an internal representation (such as `ClassName.MEMBER_NAME`) rather than the underlying primitive value. This breaks the substitutability contract: the wrapper is designed to be transparently interchangeable with the primitive it wraps, but its string representation diverges from the raw value. The inconsistency becomes especially visible when comparing in-memory wrapper instances against values that have been round-tripped through a persistence layer (database, serializer, cache), where the wrapper is stripped and only the raw primitive survives.

## Root Cause Analysis

The fundamental issue is an **implicit assumption violation** in the type hierarchy. When a class like `class MyEnum(str, Enum)` is defined, developers assume that because `str` is mixed in, all string-related behavior — including `__str__` — will delegate to the `str` primitive. In reality, Python's MRO resolves `__str__` through the `Enum` base class first (since `Enum.__str__` is explicitly defined), producing output like `"MyEnum.VALUE"` instead of the raw string `"value"`.

This is a **leaky abstraction**: the wrapper's internal identity (its enum member name and class) leaks through the string representation, violating the contract that the wrapper should behave identically to the primitive it wraps. The persistence layer exposes this gap because it stores and returns only the raw primitive value, meaning `str(instance)` before persistence differs from `str(retrieved_value)` after persistence — a classic **inconsistent-state** failure.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `str(wrapper_instance)` produces a different result than `str(raw_primitive_value)` (e.g., `"Status.ACTIVE"` vs `"active"`)
  - Template rendering, logging, URL construction, or API serialization unexpectedly includes the class/member name instead of the raw value
  - Values behave correctly after a database round-trip but incorrectly when used directly from in-memory enum/wrapper instances
  - String comparisons or dictionary lookups silently fail because the string representation doesn't match the expected primitive form

### 解决步骤
1. **Inspect the MRO** of the wrapper type (`WrapperClass.__mro__`) and identify which ancestor's `__str__` is being resolved. Confirm that a non-primitive base class (e.g., `Enum`) is winning the resolution over the primitive type (e.g., `str`).
2. **Verify the substitutability contract**: assert that the design intent is for `str(wrapper_instance)` to produce identical output to `str(primitive_value)`. If the wrapper is meant to be a transparent stand-in, any divergence is a bug.
3. **Override `__str__` at the lowest common base class** of all wrapper variants — not on individual subclasses or on consumer-side code (field descriptors, serializers, formatters). The override should return the primitive representation, e.g., `self.value` for enums.
4. **Propagate the fix uniformly**: by placing the override on the base class, all subclasses inherit the corrected behavior without duplication, and all contexts (templates, logging, f-strings, `%s` formatting, API serialization) are covered.
5. **Add direct string-representation tests**: compare `str()` output of freshly constructed wrapper instances against the expected primitive string. Do not rely solely on persistence round-trip tests, as those mask the issue by stripping the wrapper.

### Why This Works

The wrapper type's string representation is a core part of its substitutability contract with the primitive it wraps. By explicitly overriding `__str__` at the base class level, we reassert control over MRO resolution and ensure the primitive's value — not the wrapper's internal identity — is what surfaces in all string contexts. This follows the principle of **single responsibility**: the wrapper type itself owns its string representation contract, rather than pushing that responsibility to every consumer that might call `str()`.

## Boundary Cases

- **Mixed-in types with custom `__format__`**: overriding `__str__` alone may not be sufficient if `__format__` is also inherited from the non-primitive base class; verify that f-string and `.format()` behavior is also correct.
- **Composite wrappers** (e.g., `Flag` enums with bitwise combinations): `str()` on a combined flag value may need special handling since the combined value may not correspond to a single member name or primitive.
- **Subclasses that intentionally want the non-primitive `__str__`**: the base-class override should be designed so that subclasses can still opt out if they genuinely need the internal representation (e.g., for debugging).
- **`__repr__` vs `__str__` confusion**: ensure `__repr__` retains the detailed internal representation for debugging purposes while `__str__` returns the primitive value — these two methods serve different contracts.
- **Non-string primitives** (e.g., `IntEnum`): the same MRO issue applies to `int`-based wrappers; `str(IntEnum.MEMBER)` may produce `"ClassName.MEMBER"` instead of the integer's string form.

## PR Examples

- **django__django-11964**: Django's enum types (e.g., `TextChoices`, `IntegerChoices`) inherited from both `str`/`int` and `Enum`, causing `str()` to return `"EnumClass.MEMBER"` instead of the raw value. The fix overrode `__str__` on the `Choices` base class to return the primitive value, ensuring consistent behavior across templates, serialization, and database round-trips.