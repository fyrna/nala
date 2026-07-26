# checker/type_compat.py
"""
Type compatibility checking.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TypeKind:
    pass


@dataclass(frozen=True)
class PrimitiveKind(TypeKind):
    name: str


@dataclass(frozen=True)
class ArrayKind(TypeKind):
    size: int
    element: TypeKind


@dataclass(frozen=True)
class NamedKind(TypeKind):
    name: str


@dataclass(frozen=True)
class UnknownKind(TypeKind):
    raw: str


_PRIMITIVE_NAMES = frozenset({
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    "f32", "f64",
    "isize", "usize", "float",
    "bool", "string", "str", "void", "unit",
})

_ALIAS_TO_CANONICAL = {
    "str": "string",
}

_INTEGER_TYPE_NAMES = frozenset({
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    "isize", "usize",
})

_FLOAT_TYPE_NAMES = frozenset({"f32", "f64", "float"})


def is_integer_type_name(type_name: str | None) -> bool:
    return type_name in _INTEGER_TYPE_NAMES


def is_float_type_name(type_name: str | None) -> bool:
    return type_name in _FLOAT_TYPE_NAMES


def parse_type_kind(type_name: str | None) -> TypeKind:
    if type_name is None:
        return UnknownKind(raw="<none>")

    type_name = type_name.strip()

    if type_name.startswith("["):
        close = type_name.find("]")
        if close == -1:
            return UnknownKind(raw=type_name)
        size_str = type_name[1:close]
        element_str = type_name[close + 1:]
        if not size_str.isdigit():
            return UnknownKind(raw=type_name)
        size = int(size_str)
        element_kind = parse_type_kind(element_str)
        if isinstance(element_kind, UnknownKind):
            return UnknownKind(raw=type_name)
        return ArrayKind(size=size, element=element_kind)

    if type_name in _PRIMITIVE_NAMES:
        canonical_name = _ALIAS_TO_CANONICAL.get(type_name, type_name)
        return PrimitiveKind(name=canonical_name)

    if type_name.isidentifier():
        return NamedKind(name=type_name)

    return UnknownKind(raw=type_name)


def types_compatible(expected: TypeKind, actual: TypeKind) -> bool:
    if isinstance(expected, UnknownKind) or isinstance(actual, UnknownKind):
        return False

    if isinstance(expected, PrimitiveKind) and isinstance(actual, PrimitiveKind):
        return expected.name == actual.name

    if isinstance(expected, ArrayKind) and isinstance(actual, ArrayKind):
        return (
            expected.size == actual.size
            and types_compatible(expected.element, actual.element)
        )

    if isinstance(expected, NamedKind) and isinstance(actual, NamedKind):
        return expected.name == actual.name

    return False


def types_compatible_str(expected_name: str | None, actual_name: str | None) -> bool:
    return types_compatible(
        parse_type_kind(expected_name),
        parse_type_kind(actual_name),
    )
