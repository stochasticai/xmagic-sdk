"""A JSON Schema file as the pydantic model ``response_format=`` takes.

The provider interface takes a pydantic class, on purpose (DESIGN.md §14.1):
the class is the schema *and* the parser. A shell has no way to write one, so
``xmagic chat --schema`` reads a JSON Schema file and builds the class here,
for the subset a response format actually uses -- an object of typed,
described properties, nested objects and arrays, enums, and optional fields.

Anything outside that subset is refused with the keyword named, rather than
dropped: a ``pattern`` the vendor never sees is a constraint the caller
believes is enforced and is not.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, create_model

_SCALARS: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "null": type(None),
}

# JSON Schema keywords with a pydantic `Field` equivalent, and the name there.
_CONSTRAINTS: dict[str, str] = {
    "minimum": "ge",
    "maximum": "le",
    "exclusiveMinimum": "gt",
    "exclusiveMaximum": "lt",
    "minLength": "min_length",
    "maxLength": "max_length",
    "pattern": "pattern",
    "minItems": "min_length",
    "maxItems": "max_length",
}

# Keywords that shape a value and are handled here by name.
_STRUCTURAL = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "const",
    "anyOf",
    "description",
    "title",
    "default",
    "additionalProperties",
    "$schema",
    "$id",
    "examples",
}


class SchemaError(ValueError):
    """The schema file is unreadable, or uses more of JSON Schema than is mapped."""


def load_schema_model(path: str | Path) -> type[BaseModel]:
    """Read a JSON Schema file and return a pydantic model class for it."""
    p = Path(path)
    try:
        schema = json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise SchemaError(f"cannot read schema file {p}: {e.strerror or e}") from e
    except json.JSONDecodeError as e:
        raise SchemaError(f"{p} is not valid JSON: {e}") from e
    if not isinstance(schema, dict):
        raise SchemaError(f"{p}: a JSON Schema is an object, not a {type(schema).__name__}")
    return schema_to_model(schema, default_name=_model_name(p.stem))


def schema_to_model(schema: dict[str, Any], default_name: str = "Answer") -> type[BaseModel]:
    """A pydantic model for an object schema, built recursively."""
    _check_keywords(schema, where="the root")
    if schema.get("type", "object") != "object":
        raise SchemaError(
            f"the root schema must be an object, not {schema.get('type')!r}: "
            "a response format is a set of named fields"
        )
    return _object_model(
        schema, name=_model_name(schema.get("title") or default_name), where="the root"
    )


def _object_model(schema: dict[str, Any], name: str, where: str) -> type[BaseModel]:
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise SchemaError(f"{where} needs a non-empty 'properties' object")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(k, str) for k in required):
        raise SchemaError(f"{where}: 'required' must be a list of property names")
    unknown = sorted(set(required) - set(properties))
    if unknown:
        raise SchemaError(f"{where}: 'required' names properties that do not exist: {unknown}")

    fields: dict[str, Any] = {}
    for key, prop in properties.items():
        if not isinstance(prop, dict):
            raise SchemaError(f"property {key!r} under {where} must be a schema object")
        here = f"property {key!r}"
        annotation = _annotation(prop, name=_model_name(f"{name}_{key}"), where=here)
        kwargs: dict[str, Any] = {}
        if "description" in prop:
            kwargs["description"] = prop["description"]
        for keyword, field_kw in _CONSTRAINTS.items():
            if keyword in prop:
                kwargs[field_kw] = prop[keyword]
        if key in required:
            default: Any = ...
        elif "default" in prop:
            default = prop["default"]
        else:
            # Absent in JSON is `None` here: the vendor may leave it out and
            # the caller reads `None` rather than an AttributeError.
            annotation = Union[annotation, None]  # noqa: UP007 - runtime type for create_model
            default = None
        fields[key] = (annotation, Field(default, **kwargs))
    return create_model(name, **fields)


def _annotation(prop: dict[str, Any], name: str, where: str) -> Any:
    """The Python type for one property schema."""
    _check_keywords(prop, where)
    if "const" in prop:
        return Literal[prop["const"]]
    if "enum" in prop:
        values = prop["enum"]
        if not isinstance(values, list) or not values:
            raise SchemaError(f"{where}: 'enum' must be a non-empty list")
        return Literal[tuple(values)]
    if "anyOf" in prop:
        options = prop["anyOf"]
        if not isinstance(options, list) or not options:
            raise SchemaError(f"{where}: 'anyOf' must be a non-empty list")
        members = tuple(
            _annotation(option, name=f"{name}Option{i}", where=f"{where} anyOf[{i}]")
            for i, option in enumerate(options)
        )
        return Union[members]  # noqa: UP007 - runtime type for create_model
    kind = prop.get("type")
    if isinstance(kind, list):
        members = tuple(_annotation({**prop, "type": t}, name=name, where=where) for t in kind)
        return Union[members]  # noqa: UP007 - runtime type for create_model
    if kind == "object":
        return _object_model(prop, name=name, where=where)
    if kind == "array":
        items = prop.get("items")
        if not isinstance(items, dict):
            raise SchemaError(f"{where}: an array needs an 'items' schema")
        return list[_annotation(items, name=f"{name}Item", where=f"{where} items")]  # type: ignore[misc]
    if kind in _SCALARS:
        return _SCALARS[kind]
    if kind is None:
        raise SchemaError(f"{where} has no 'type' (and no enum, const, or anyOf)")
    raise SchemaError(f"{where}: unsupported type {kind!r}")


def _check_keywords(schema: dict[str, Any], where: str) -> None:
    unsupported = sorted(k for k in schema if k not in _STRUCTURAL and k not in _CONSTRAINTS)
    if unsupported:
        raise SchemaError(
            f"{where} uses JSON Schema keywords --schema does not map: {', '.join(unsupported)}. "
            "Supported: object/array/string/integer/number/boolean/null types, "
            "properties, required, items, enum, const, anyOf, description, default, "
            "and the min/max/length/pattern constraints."
        )


def _model_name(raw: str) -> str:
    """An identifier for the generated class; it is also the schema name sent."""
    cleaned = re.sub(r"\W+", "_", raw).strip("_") or "Answer"
    return cleaned if not cleaned[0].isdigit() else f"_{cleaned}"
