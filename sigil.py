"""Small interpreter for the documented Sigil language syntax."""
from __future__ import annotations

import ast
import colorsys
import copy
import datetime as dt
import difflib
import re
import random
import sys
from dataclasses import dataclass


# One-argument calls that work on the argument's text: #name(x) -> (name, function on str).
TEXT_CALLS = {
    "__len": ("len", len),
    "__lower": ("lower", str.lower),
    "__upper": ("upper", str.upper),
    "__num": ("num", lambda text: to_number(text)),  # lambda: to_number is defined further down
}
TEXT_CALL_NAMES = tuple(name for name, _ in TEXT_CALLS.values())
# Two-argument calls: #name(a, b) -> (name, usage shown in error messages).
PAIR_CALLS = {
    "__add": ("add", "(list, value)"),
    "__join": ("join", "(list, separator)"),
    "__split": ("split", "(text, separator)"),
}
SYSTEM_CALLS = ("date", "rnd") + tuple(name for name, _ in PAIR_CALLS.values()) + TEXT_CALL_NAMES
MAX_LOOP_ITERATIONS = 1_000_000
MAX_SEQUENCE_LENGTH = 1_000_000  # cap for '*' repetition of text and lists


class SigilError(Exception):
    pass


class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


@dataclass
class Line:
    indent: int
    text: str
    number: int


def strip_comment(raw: str) -> str:
    """Cut a ';' comment off a line. A ';' inside a '...' string is ordinary text."""
    in_string = False
    for position, char in enumerate(raw):
        if char == "'":
            in_string = not in_string
        elif char == ";" and not in_string:
            return raw[:position]
    return raw


def parse_lines(source: str) -> list[Line]:
    result = []
    for number, raw in enumerate(source.splitlines(), 1):
        raw = strip_comment(raw)
        if not raw.strip():
            continue
        prefix = raw[:len(raw) - len(raw.lstrip(" \t"))]
        expanded = prefix.replace("\t", "    ")
        if len(expanded) % 4:
            raise SigilError(f"line {number}: indentation must use tabs or groups of four spaces")
        result.append(Line(len(expanded) // 4, raw.strip(), number))
    return result


def split_block(lines: list[Line], index: int, indent: int):
    """Return statements at this indentation and the first unconsumed line."""
    statements = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise SigilError(f"line {line.number}: unexpected indentation")
        function_match = re.fullmatch(r"\$([A-Za-z_][A-Za-z_0-9]*)\((.*?)\):", line.text)
        if function_match:
            params = [part.strip() for part in function_match.group(2).split(",") if part.strip()]
            if any(not re.fullmatch(r"%[A-Za-z_][A-Za-z_0-9]*", param) for param in params):
                raise SigilError(f"line {line.number}: function parameters must be %variables")
            if len({p.lower() for p in params}) != len(params):
                raise SigilError(f"line {line.number}: duplicate function parameter")
            index += 1
            if index >= len(lines) or lines[index].indent <= indent:
                raise SigilError(f"line {line.number}: expected an indented function body")
            body_indent = lines[index].indent
            body, index = split_block(lines, index, body_indent)
            statements.append(("function", (function_match.group(1), [p[1:] for p in params], body), line.number))
            continue
        if line.text.startswith("? ") and line.text.endswith(":"):
            branches = []
            condition = line.text[2:-1].strip()
            index += 1
            if index >= len(lines) or lines[index].indent <= indent:
                raise SigilError(f"line {line.number}: expected an indented condition body")
            body_indent = lines[index].indent
            body, index = split_block(lines, index, body_indent)
            branches.append((condition, body))
            while index < len(lines) and lines[index].indent == indent:
                marker = lines[index]
                if marker.text == ">":
                    index += 1
                    if index >= len(lines) or lines[index].indent <= indent:
                        raise SigilError(f"line {marker.number}: expected an indented else body")
                    else_indent = lines[index].indent
                    body, index = split_block(lines, index, else_indent)
                    branches.append((None, body))
                    break
                elif marker.text.startswith("> ? ") and marker.text.endswith(":"):
                    condition = marker.text[4:-1].strip()
                    index += 1
                    if index >= len(lines) or lines[index].indent <= indent:
                        raise SigilError(f"line {marker.number}: expected an indented else-if body")
                    branch_indent = lines[index].indent
                    body, index = split_block(lines, index, branch_indent)
                    branches.append((condition, body))
                else:
                    break
            statements.append(("if", branches, line.number))
            continue
        if line.text.startswith("@") and line.text.endswith(":"):
            condition = line.text[1:-1].strip()
            if not condition:
                raise SigilError(f"line {line.number}: loop condition is empty")
            index += 1
            if index >= len(lines) or lines[index].indent <= indent:
                raise SigilError(f"line {line.number}: expected an indented loop body")
            body_indent = lines[index].indent
            body, index = split_block(lines, index, body_indent)
            statements.append(("while", (condition, body), line.number))
            continue
        if line.text.startswith(":<"):
            statements.append(("return", line.text[2:].strip(), line.number))
            index += 1
            continue
        if line.text == ">" or line.text.startswith("> ? "):
            raise SigilError(f"line {line.number}: else branch without a matching condition")
        statements.append(("line", line.text, line.number))
        index += 1
    return statements, index


def prepare_code(code: str) -> str:
    """Translate Sigil syntax to Python syntax in a fragment that is outside string literals."""
    for call in re.findall(r"#([A-Za-z_][A-Za-z_0-9]*)", code):
        if call not in SYSTEM_CALLS:
            hint = difflib.get_close_matches(call, SYSTEM_CALLS, n=1)
            suffix = f" (did you mean #{hint[0]}?)" if hint else ""
            raise SigilError(f"unknown system call: #{call}{suffix}")
    code = re.sub(r"#date\b", "__sys_date", code)
    code = re.sub(r"#rnd\b", "__rnd", code)
    for name, _ in PAIR_CALLS.values():
        code = re.sub(rf"#{name}\b", f"__{name}", code)
    for name in TEXT_CALL_NAMES:
        code = re.sub(rf"#{name}\b", f"__{name}", code)
    code = re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)", r"__fn_\1", code)
    code = re.sub(
        r"(?<!\w)(\d{1,2})\.(\d{1,2})\.(\d{4})\b",
        lambda m: repr(dt.datetime(int(m[3]), int(m[2]), int(m[1]))), code,
    )
    code = re.sub(r"%([A-Za-z_][A-Za-z_0-9]*)", r"\1", code)
    code = re.sub(r"\btrue\b", "True", code)
    code = re.sub(r"\bfalse\b", "False", code)
    # '!~' must be translated before the generic '!' rule below.
    code = code.replace("!~", " not in ").replace("~", " in ")
    code = re.sub(r"!(?!=)", " not ", code)
    code = code.replace("&", " and ").replace("|", " or ")
    return code


def prepare_expr(expression: str, env: dict):
    # String literals are kept verbatim: no Sigil substitution happens inside quotes.
    parts = re.split(r"('[^']*')", expression)
    out = []
    for i, part in enumerate(parts):
        out.append(repr(part[1:-1]) if i % 2 else prepare_code(part))
    return "".join(out).strip()


def evaluate(expression: str, env: dict, functions=None):
    functions = functions if functions is not None else {}
    expression = prepare_expr(expression, env)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SigilError(f"invalid expression: {expression}") from exc

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == "__sys_date":
                return dt.date.today()
            if node.id in TEXT_CALLS:
                raise SigilError(f"#{TEXT_CALLS[node.id][0]} expects exactly one argument")
            if node.id in PAIR_CALLS:
                name, usage = PAIR_CALLS[node.id]
                raise SigilError(f"#{name} expects exactly two arguments {usage}")
            if node.id == "__rnd":
                return random.SystemRandom().randint(0, 100)
            if node.id not in env:
                raise SigilError(f"undefined variable: %{node.id}")
            return env[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add) and (isinstance(left, str) or isinstance(right, str)):
                return sigil_string(left) + sigil_string(right)
            if isinstance(node.op, ast.Mult):
                for sequence, times in ((left, right), (right, left)):
                    if isinstance(sequence, (str, list)) and isinstance(times, int) and len(sequence) * max(times, 0) > MAX_SEQUENCE_LENGTH:
                        raise SigilError(f"result would exceed {MAX_SEQUENCE_LENGTH:,} elements")
            return BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.List):
            return [copy_value(visit(element)) for element in node.elts]
        if isinstance(node, ast.Subscript):
            container, index = visit(node.value), visit(node.slice)
            if not isinstance(container, (list, str)):
                raise SigilError("only lists and text can be indexed")
            return container[check_index(index, len(container))]
        if isinstance(node, ast.BoolOp):
            is_and = isinstance(node.op, ast.And)
            result = None
            for operand in node.values:
                result = visit(operand)
                if bool(result) != is_and:
                    break
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARYOPS:
            return UNARYOPS[type(node.op)](visit(node.operand))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            # '~' / '!~': element of a list, otherwise substring of the text.
            # In text, an empty left side is never "inside" anything.
            left, right = visit(node.left), visit(node.comparators[0])
            if isinstance(right, list):
                found = any(values_equal(left, item) for item in right)
            else:
                needle = sigil_string(left)
                found = bool(needle) and needle in sigil_string(right)
            return found if isinstance(node.ops[0], ast.In) else not found
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in CMPOPS:
            left, right = visit(node.left), visit(node.comparators[0])
            if isinstance(left, str) or isinstance(right, str):
                left, right = sigil_string(left), sigil_string(right)
            return CMPOPS[type(node.ops[0])](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__rnd":
            args = [visit(arg) for arg in node.args]
            if len(args) == 0:
                return random.SystemRandom().randint(0, 100)
            if len(args) == 1 and isinstance(args[0], str) and args[0]:
                return random.SystemRandom().choice(args[0])
            if len(args) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in args):
                low, high = args
                if low > high:
                    raise SigilError("#rnd lower bound must not exceed upper bound")
                return random.SystemRandom().randint(low, high)
            if len(args) == 2 and isinstance(args[0], int) and isinstance(args[1], str) and args[0] >= 0 and args[1]:
                chooser = random.SystemRandom()
                return "".join(chooser.choice(args[1]) for _ in range(args[0]))
            raise SigilError("#rnd expects no arguments, (min, max), (alphabet), or (length, alphabet)")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in TEXT_CALLS:
            name, function = TEXT_CALLS[node.func.id]
            if len(node.args) != 1:
                raise SigilError(f"#{name} expects exactly one argument")
            argument = visit(node.args[0])
            if name == "len" and isinstance(argument, list):
                return len(argument)
            if name == "num" and isinstance(argument, (int, float)) and not isinstance(argument, bool):
                return argument  # already a number: pass it through unchanged (no text round trip)
            return function(sigil_string(argument))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PAIR_CALLS:
            name, usage = PAIR_CALLS[node.func.id]
            args = [visit(arg) for arg in node.args]
            if len(args) != 2:
                raise SigilError(f"#{name} expects exactly two arguments {usage}")
            first, second = args
            if name in ("add", "join") and not isinstance(first, list):
                raise SigilError(f"#{name} expects a list as the first argument")
            if name == "add":
                return first + [copy_value(second)]  # lists are values: a new list is returned
            if name == "join":
                return sigil_string(second).join(sigil_string(item) for item in first)
            text, separator = sigil_string(first), sigil_string(second)
            return list(text) if separator == "" else text.split(separator)  # '' splits into characters
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("__fn_"):
            name = node.func.id[5:]
            if name not in functions:
                raise SigilError(f"undefined function: ${name}")
            params, body = functions[name]
            if len(node.args) != len(params):
                raise SigilError(f"${name} expects {len(params)} argument(s), got {len(node.args)}")
            local_env = {key: copy_value(value) for key, value in env.items()}
            for param, arg in zip(params, node.args):
                local_env[param] = copy_value(visit(arg))
            try:
                run(body, local_env, functions, in_function=True)
            except ReturnSignal as returned:
                return returned.value
            return None
        raise SigilError("unsupported expression")

    try:
        return visit(tree)
    except ZeroDivisionError as exc:
        raise SigilError("division by zero") from exc
    except TypeError as exc:
        raise SigilError(f"invalid operation: {exc}") from exc


import operator
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
CMPOPS = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}


def read_value(prompt: str = ""):
    try:
        raw = input(prompt)
    except EOFError as exc:
        raise SigilError("input ended before a value was entered") from exc
    number = parse_number(raw)
    return raw if number is None else number


def parse_number(text: str):
    """The one place that decides what a number looks like: [+-]digits, optionally with a '.' part.
    Returns int / float, or None if the text is not a number. ASCII digits only; no exponent, no comma."""
    value = text.strip()
    if re.fullmatch(r"[+-]?[0-9]+", value):
        return int(value)
    if re.fullmatch(r"[+-]?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)", value):
        return float(value)
    return None


def to_number(text: str):
    number = parse_number(text)
    if number is None:
        raise SigilError(f"#num cannot convert {text!r} to a number")
    return number


def sigil_string(value):
    if isinstance(value, dt.datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, list):
        # Same notation as a list literal: text in quotes, numbers bare.
        return "[" + ", ".join(f"'{item}'" if isinstance(item, str) else sigil_string(item) for item in value) + "]"
    return str(value)


def copy_value(value):
    """Lists are values, not references: every store of a list makes its own copy."""
    return copy.deepcopy(value) if isinstance(value, list) else value


def values_equal(left, right) -> bool:
    """Equality as '==' sees it: if either side is text, compare both as text."""
    if isinstance(left, str) or isinstance(right, str):
        return sigil_string(left) == sigil_string(right)
    return left == right


def check_index(index, length: int) -> int:
    if isinstance(index, bool) or not isinstance(index, int):
        raise SigilError("index must be a whole number")
    if not 0 <= index < length:
        raise SigilError(f"index {index} out of range (length {length})")
    return index


def find_assignment(text: str) -> int:
    """Position of the '=' of an assignment (outside quotes/brackets, not part of ==, !=, <=, >=), else -1."""
    depth, in_string, i = 0, False, 0
    while i < len(text):
        char = text[i]
        if char == "'":
            in_string = not in_string
        elif not in_string:
            if char in "[(":
                depth += 1
            elif char in "])":
                depth -= 1
            elif text[i:i + 2] == "==":
                i += 1  # skip both characters of '=='
            elif char == "=" and depth == 0 and (i == 0 or text[i - 1] not in "!<>"):
                return i
        i += 1
    return -1


def parse_target(target: str):
    """'%name' or '%name[i][j]' -> (name, [index expression, ...])."""
    match = re.match(r"%([A-Za-z_][A-Za-z_0-9]*)", target)
    if not match:
        raise SigilError("assignment target must be a %variable or a %list[index]")
    name, rest, indexes = match.group(1), target[match.end():], []
    pos = 0
    while pos < len(rest):
        if rest[pos].isspace():
            pos += 1
            continue
        if rest[pos] != "[":
            raise SigilError("assignment target must be a %variable or a %list[index]")
        depth, in_string, end = 0, False, None
        for j in range(pos, len(rest)):
            if rest[j] == "'":
                in_string = not in_string
            elif not in_string and rest[j] == "[":
                depth += 1
            elif not in_string and rest[j] == "]":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None or not rest[pos + 1:end].strip():
            raise SigilError("assignment target has an empty or unclosed [index]")
        indexes.append(rest[pos + 1:end])
        pos = end + 1
    return name, indexes


def assign_indexed(env, name, index_expressions, value, functions):
    if name not in env:
        raise SigilError(f"undefined variable: %{name}")
    container = env[name]
    indexes = [evaluate(expression, env, functions) for expression in index_expressions]
    for index in indexes[:-1]:
        if not isinstance(container, (list, str)):
            raise SigilError("only lists and text can be indexed")
        container = container[check_index(index, len(container))]
    if not isinstance(container, list):
        raise SigilError("only list elements can be assigned (text is read-only)")
    container[check_index(indexes[-1], len(container))] = value


def hustl_console_color(code: str) -> int:
    """Map a HUSTL field coordinate to the nearest xterm-256 palette entry."""
    match = re.fullmatch(r"([A-Z])([0-9])(?:\.(\d+))?", code)
    if not match:
        raise SigilError(f"invalid HUSTL color code: {code}")
    hue_letter = match.group(1)
    saturation_digit = int(match.group(2))
    intervals = [
        [(ord(hue_letter) - ord("A")) / 26, (ord(hue_letter) - ord("A") + 1) / 26],
        [saturation_digit / 10, (saturation_digit + 1) / 10],
        [0.0, 1.0],
    ]
    for index, digit in enumerate(match.group(3) or ""):
        axis = index % 3
        low, high = intervals[axis]
        width = (high - low) / 10
        start = low + int(digit) * width
        intervals[axis] = [start, start + width]
    hue, saturation, lightness = (sum(interval) / 2 for interval in intervals)
    red, green, blue = (round(channel * 255) for channel in colorsys.hls_to_rgb(hue, lightness, saturation))

    palette = []
    levels = (0, 95, 135, 175, 215, 255)
    for r in levels:
        for g in levels:
            for b in levels:
                palette.append((r, g, b))
    palette.extend((v, v, v) for v in range(8, 239, 10))
    nearest = min(range(len(palette)), key=lambda i: sum((palette[i][c] - (red, green, blue)[c]) ** 2 for c in range(3)))
    return nearest + 16


def run(statements, env, functions=None, in_function=False):
    functions = functions if functions is not None else {}
    for kind, payload, number in statements:
        try:
            if kind == "function":
                name, params, body = payload
                functions[name] = (params, body)
                continue
            if kind == "return":
                if not in_function:
                    raise SigilError(":< can only be used inside a function")
                value = evaluate(payload, env, functions) if payload else None
                raise ReturnSignal(value)
            if kind == "if":
                for condition, body in payload:
                    if condition is None or evaluate(condition, env, functions):
                        run(body, env, functions, in_function)
                        break
                continue
            if kind == "while":
                condition, body = payload
                iterations = 0
                while evaluate(condition, env, functions):
                    iterations += 1
                    if iterations > MAX_LOOP_ITERATIONS:
                        raise SigilError(f"loop exceeded {MAX_LOOP_ITERATIONS:,} iterations")
                    run(body, env, functions, in_function)
                continue
            text = payload
            if text.startswith("<:"):
                read_value()
            elif text.startswith(">:"):
                output = text[2:].strip()
                color_match = re.match(r"^([A-Z][0-9](?:\.\d+)?)\s+(.+)$", output)
                color = hustl_console_color(color_match.group(1)) if color_match else None
                expression = color_match.group(2) if color_match else output
                value = evaluate(expression, env, functions)
                if isinstance(value, (dt.date, dt.datetime, list)):
                    value = sigil_string(value)
                if color is None:
                    print(value)
                else:
                    print(f"\x1b[38;5;{color}m{value}\x1b[0m")
            elif text == ":" or text.startswith(": "):
                # The docs describe ':' as a continuation marker, not output.
                pass
            elif find_assignment(text) >= 0:
                equals = find_assignment(text)
                name, index_expressions = parse_target(text[:equals].strip())
                expression = text[equals + 1:].strip()
                value = read_value() if expression == "<:" else evaluate(expression, env, functions)
                value = copy_value(value)
                if index_expressions:
                    assign_indexed(env, name, index_expressions, value, functions)
                else:
                    env[name] = value
            else:
                raise SigilError(f"unknown statement: {text}")
        except ReturnSignal:
            raise
        except SigilError as exc:
            if getattr(exc, "located", False):
                raise  # already carries the innermost line number
            located = SigilError(f"line {number}: {exc}")
            located.located = True
            raise located from exc


def main():
    if len(sys.argv) != 2:
        print("Usage: python sigil.py <program.sg>", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as source_file:
            lines = parse_lines(source_file.read())
        statements, index = split_block(lines, 0, 0)
        if index != len(lines):
            raise SigilError("could not parse the whole program")
        run(statements, {}, {})
    except RecursionError:
        print("Sigil error: recursion too deep", file=sys.stderr)
        return 1
    except (OSError, SigilError) as exc:
        print(f"Sigil error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
