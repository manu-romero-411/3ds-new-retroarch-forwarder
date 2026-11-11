"""A core's options, read from its ``libretro_core_options.h``.

Every libretro core declares its options as a static C array
(``option_defs_us``, core options v1 or v2). The bases ship that header
(``bases/<core>/core_options.h``) and this module reads it without a C
compiler: a small preprocessor keeps the branches a 3DS build compiles
(:data:`CTR_DEFINES`), then the array initializer is parsed as nested
braces. The result feeds the core options dialog, and a game's chosen
values are written as ``game.opt`` (RetroArch's core options file).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Macros a ``platform=ctr`` core build defines that option headers test.
CTR_DEFINES: dict[str, str] = {
    "_3DS": "1",
    "ARM": "1",
    "__arm__": "1",
    "HAVE_DYNAREC": "1",
    "HAVE_NO_LANGEXTRA": "1",
}

_DEFINITION_TYPES = ("retro_core_option_v2_definition", "retro_core_option_definition")
_CATEGORY_TYPE = "retro_core_option_v2_category"
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_DIRECTIVE = re.compile(r"^\s*#\s*(\w+)\s*(.*)$")
_FUNCTION_MACRO = re.compile(r"(\w+)\((\w+)\)\s+(.*)")
_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[A-Za-z_]\w*|\d\w*|[{}(),;=\[\]#]|\S')


class CoreOptionsError(ValueError):
    """The header has no option definitions this module can read."""


@dataclass(frozen=True)
class CoreOption:
    """One option: its key, label, help text and allowed values."""

    key: str
    label: str
    info: str
    category: str
    #: ``(value, label)`` pairs, in the core's order.
    values: tuple[tuple[str, str], ...]
    default: str

    def label_of(self, value: str) -> str:
        """The display label of ``value`` (the value itself when it has none)."""
        for candidate, label in self.values:
            if candidate == value:
                return label
        return value


@dataclass
class CoreOptions:
    """Every option of a core, plus the display names of its categories."""

    options: list[CoreOption] = field(default_factory=list)
    categories: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> CoreOption | None:
        """The option called ``key``, if the core has it."""
        return next((option for option in self.options if option.key == key), None)

    def category_label(self, key: str) -> str:
        """The display name of category ``key`` (``""`` for uncategorized)."""
        return self.categories.get(key, key)

    def defaults(self) -> dict[str, str]:
        """Every option at its default value."""
        return {option.key: option.default for option in self.options}

    def clean(self, values: dict[str, str]) -> dict[str, str]:
        """``values`` minus unknown keys, invalid values and defaults."""
        result = {}
        for key, value in values.items():
            option = self.get(key)
            if option is None or value == option.default:
                continue
            if any(value == candidate for candidate, _label in option.values):
                result[key] = value
        return result


# ── Preprocessing ────────────────────────────────────────────────────────


def _condition(expression: str, defines: dict[str, str]) -> bool:
    """Evaluate a ``#if`` expression; unknown macros are 0, like in C."""
    text = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)", _defined_sub(defines), expression)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    text = re.sub(r"[A-Za-z_]\w*", _macro_sub(defines), text)
    try:
        return bool(eval(text, {"__builtins__": {}}, {}))  # pylint: disable=eval-used
    except (SyntaxError, NameError, TypeError, ZeroDivisionError):
        return True  # keep what cannot be decided: it is only listed, not compiled


def _defined_sub(defines: dict[str, str]):
    def replace(match: re.Match[str]) -> str:
        return "1" if (match.group(1) or match.group(2)) in defines else "0"

    return replace


def _macro_sub(defines: dict[str, str]):
    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if word in ("and", "or", "not"):
            return word
        value = defines.get(word, "0").strip() or "1"
        return value if re.fullmatch(r"\d+", value) else "1"

    return replace


def preprocess(  # pylint: disable=too-many-branches
    text: str, defines: dict[str, str] | None = None
) -> str:
    """``text`` without comments, directives and the branches not compiled.

    Simple function-like macros of one argument (``#define V(x) { #x, NULL }``,
    used by some cores for value lists) are expanded.
    """
    defines = dict(CTR_DEFINES if defines is None else defines)
    macros: dict[str, tuple[str, str]] = {}
    text = _COMMENT.sub(" ", text.replace("\\\n", " "))
    output: list[str] = []
    # Each entry: (this branch active, some branch taken, parent active).
    stack: list[tuple[bool, bool, bool]] = []
    active = True
    for line in text.splitlines():
        match = _DIRECTIVE.match(line)
        if match is None:
            if active:
                output.append(line)
            continue
        name, rest = match.group(1), match.group(2).strip()
        if name in ("if", "ifdef", "ifndef"):
            if name == "ifdef":
                value = rest.split()[0] in defines if rest else False
            elif name == "ifndef":
                value = rest.split()[0] not in defines if rest else True
            else:
                value = _condition(rest, defines)
            stack.append((active and value, value, active))
            active = active and value
        elif name == "elif" and stack:
            _branch, taken, parent = stack.pop()
            value = not taken and _condition(rest, defines)
            stack.append((parent and value, taken or value, parent))
            active = parent and value
        elif name == "else" and stack:
            _branch, taken, parent = stack.pop()
            stack.append((parent and not taken, True, parent))
            active = parent and not taken
        elif name == "endif" and stack:
            active = stack.pop()[2]
        elif name == "define" and active and rest:
            function = _FUNCTION_MACRO.match(rest)
            if function:
                macros[function.group(1)] = (function.group(2), function.group(3))
            else:
                key, _sep, value = rest.partition(" ")
                defines[key] = value.strip()
        elif name == "undef" and active:
            defines.pop(rest, None)
    return _expand(" \n".join(output), macros)


def _expand(text: str, macros: dict[str, tuple[str, str]]) -> str:
    for name, (param, body) in macros.items():

        def replace(match: re.Match[str], param: str = param, body: str = body) -> str:
            argument = match.group(1).strip()
            result = body.replace(f"#{param}", f'"{argument}"')
            return re.sub(rf"\b{param}\b", argument, result)

        text = re.sub(rf"\b{name}\(([^()]*)\)", replace, text)
    return text


# ── Parsing ──────────────────────────────────────────────────────────────


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _initializer(tokens: list[str], start: int) -> tuple[list[object], int]:
    """Parse the brace list opening at ``tokens[start]``; return it and the end index."""
    items: list[object] = []
    current: list[str] = []
    index = start + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "{":
            nested, index = _initializer(tokens, index)
            items.append(nested)
            current = []
        elif token == "}":
            if current:
                items.append(_scalar(current))
            return items, index
        elif token == ",":
            if current:
                items.append(_scalar(current))
            current = []
        else:
            current.append(token)
        index += 1
    raise CoreOptionsError("Unterminated initializer")


def _scalar(tokens: list[str]) -> str | None:
    """A string (adjacent literals concatenated), ``None`` for NULL, else the raw text."""
    strings = [token for token in tokens if token.startswith('"')]
    if strings:
        return "".join(_unquote(token) for token in strings)
    text = " ".join(tokens)
    return None if text in ("NULL", "0") else text


def _unquote(token: str) -> str:
    body = token[1:-1]
    return re.sub(
        r"\\(.)", lambda match: {"n": "\n", "t": "\t"}.get(match.group(1), match.group(1)), body
    )


def _arrays(tokens: list[str], type_name: str) -> list[list[object]]:
    """Every ``struct <type_name> name[] = { ... }`` initializer, in order."""
    found = []
    for index, token in enumerate(tokens):
        if token != type_name:
            continue
        try:
            equals = tokens.index("=", index)
            semicolon = tokens.index(";", index)
        except ValueError:
            continue
        if equals > semicolon or tokens[equals + 1] != "{":
            continue  # a declaration, filled in at run time
        items, _end = _initializer(tokens, equals + 1)
        found.append(items)
    return found


def _option(entry: list[object], version2: bool) -> CoreOption | None:
    if version2 and len(entry) >= 8:
        key, label, _label_cat, info, _info_cat, category, values, default = entry[:8]
    elif not version2 and len(entry) >= 5:
        key, label, info, values, default = entry[:5]
        category = None
    else:
        return None
    if not isinstance(key, str) or not isinstance(values, list):
        return None
    pairs = []
    for value in values:
        if isinstance(value, list) and value and isinstance(value[0], str):
            value_label = value[1] if len(value) > 1 and isinstance(value[1], str) else value[0]
            pairs.append((value[0], value_label))
    if not pairs:
        return None
    if not isinstance(default, str) or default not in (value for value, _label in pairs):
        default = pairs[0][0]
    return CoreOption(
        key=key,
        label=label if isinstance(label, str) else key,
        info=info if isinstance(info, str) else "",
        category=category if isinstance(category, str) else "",
        values=tuple(pairs),
        default=default,
    )


def parse_core_options(text: str, defines: dict[str, str] | None = None) -> CoreOptions:
    """The options declared in a ``libretro_core_options.h``.

    Raises :class:`CoreOptionsError` if it declares none.
    """
    tokens = _tokens(preprocess(text, defines))
    result = CoreOptions()
    for categories in _arrays(tokens, _CATEGORY_TYPE)[:1]:
        for entry in categories:
            if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str):
                result.categories[entry[0]] = entry[1] if isinstance(entry[1], str) else entry[0]
    seen: set[str] = set()
    for type_name in _DEFINITION_TYPES:
        arrays = _arrays(tokens, type_name)
        if not arrays:
            continue
        for entry in arrays[0]:
            if not isinstance(entry, list):
                continue
            option = _option(entry, type_name == _DEFINITION_TYPES[0])
            if option is not None and option.key not in seen:
                seen.add(option.key)
                result.options.append(option)
        break
    if not result.options:
        raise CoreOptionsError("No core option definitions found")
    return result


def load_core_options(path: Path) -> CoreOptions:
    """Read ``path``, a base's ``core_options.h``.

    Raises ``OSError`` or :class:`CoreOptionsError`.
    """
    return parse_core_options(path.read_text(encoding="utf-8", errors="replace"))


def options_file_text(values: dict[str, str]) -> str:
    """``game.opt`` with ``values`` (RetroArch's core options file format)."""
    return "".join(f'{key} = "{value}"\n' for key, value in sorted(values.items()))
