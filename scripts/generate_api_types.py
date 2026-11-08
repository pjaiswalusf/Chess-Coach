"""Regenerate frontend contracts: uv run python scripts/generate_api_types.py."""

from pathlib import Path

from chess_coach.api.app import app


def ts(schema):
    if "const" in schema:
        return repr(schema["const"])
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[1]
    if "anyOf" in schema:
        return " | ".join(ts(item) for item in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(repr(value) for value in schema["enum"])
    kind = schema.get("type")
    if kind == "array" and "prefixItems" in schema:
        return "[" + ", ".join(ts(item) for item in schema["prefixItems"]) + "]"
    if kind == "array":
        return f"Array<{ts(schema.get('items', {}))}>"
    if kind == "object":
        if "properties" in schema and not schema["properties"]:
            return "Record<string, never>"
        if "properties" in schema:
            required = schema.get("required", [])
            return (
                "{\n"
                + "\n".join(
                    f"  {key}{'' if key in required else '?'}: {ts(value)};"
                    for key, value in schema["properties"].items()
                )
                + "\n}"
            )
        more = schema.get("additionalProperties", {})
        return f"Record<string, {ts(more) if isinstance(more, dict) else 'unknown'}>"
    return {
        "integer": "number",
        "number": "number",
        "string": "string",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


schemas = app.openapi()["components"]["schemas"]
output = (
    "// Generated from FastAPI OpenAPI by scripts/generate_api_types.py. Do not edit.\n"
)
output += "\n".join(
    f"export type {name} = {ts(schema)};\n" for name, schema in schemas.items()
)
Path("frontend/src/lib/api/generated.ts").write_text(output)
