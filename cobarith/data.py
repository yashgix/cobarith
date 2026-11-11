"""PICTURE parsing, storage sizes and data-item lookup for fixed-format COBOL."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .source import Token

__all__ = [
    "DataDivision",
    "DataItem",
    "DataItems",
    "Item",
    "binary_bits",
    "data_items",
    "find_item",
    "items_from_tokens",
    "lookup",
    "parse_data",
    "parse_data_items",
    "parse_items",
    "parse_pic",
    "Pic",
    "resolve",
    "resolve_all",
]


@dataclass(frozen=True)
class Pic:
    """A parsed PICTURE clause; digits and scale are counted in decimal positions."""

    text: str
    kind: str
    digits: int
    scale: int
    signed: bool

    @property
    def capacity(self) -> int:
        """Largest magnitude in units, i.e. 10**(digits + scale) - 1."""

        return 10 ** (self.digits + self.scale) - 1


def _expand_repeats(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if i + 1 < len(text) and text[i + 1] == "(":
            end = text.find(")", i + 2)
            if end != -1 and text[i + 2 : end].isdigit():
                out.append(char * int(text[i + 2 : end]))
                i = end + 1
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _digit_count(segment: str, seen: set[str]) -> int:
    count = 0
    for char in segment:
        if char in "9Z*":
            count += 1
        elif char in "+-$":
            if char in seen:
                count += 1
            else:
                seen.add(char)
    return count


def parse_pic(text: str) -> Pic:
    """Parse a COBOL PICTURE into digits, scale, signedness and broad kind."""

    expanded = _expand_repeats(text).upper()

    if any(char in "XAN" for char in expanded):
        return Pic(text, "alnum", len(expanded), 0, False)

    if "P" in expanded:
        digits = sum(1 for char in expanded if char in "9Z*")
        signed = expanded.startswith("S") or "+" in expanded or "-" in expanded
        return Pic(text, "scaled", digits, 0, signed)

    if all(char in "S9V" for char in expanded) and "9" in expanded:
        before, _, after = expanded.partition("V")
        return Pic(
            text,
            "numeric",
            before.count("9"),
            after.count("9"),
            expanded.startswith("S"),
        )

    point = len(expanded)
    if "." in expanded:
        point = expanded.index(".")
    elif "V" in expanded:
        point = expanded.index("V")

    seen: set[str] = set()
    digits = _digit_count(expanded[:point], seen)
    scale = _digit_count(expanded[point + 1 :], seen)
    signed = "+" in expanded or "-" in expanded or "CR" in expanded or "DB" in expanded
    return Pic(text, "edited", digits, scale, signed)


def binary_bits(pic: Pic | str) -> int:
    """GnuCOBOL -std=ibm binary field width: 2, 4 or 8 bytes."""

    if isinstance(pic, str):
        pic = parse_pic(pic)
    total = pic.digits + pic.scale
    if total <= 4:
        return 16
    if total <= 9:
        return 32
    return 64


@dataclass(eq=False)
class Item:
    """One elementary item, group or index-name from the DATA DIVISION."""

    name: str
    level: int = 0
    pic: Pic | None = None
    usage: str = "DISPLAY"
    parent: Item | None = field(default=None, repr=False)
    index: bool = False
    file: str = ""
    line: int = 0
    children: list[Item] = field(default_factory=list, repr=False)

    @property
    def qualifiers(self) -> tuple[str, ...]:
        """Ancestor names, closest first; FILLER cannot be a qualifier."""

        names: list[str] = []
        node = self.parent
        while node is not None:
            if node.name.upper() != "FILLER":
                names.append(node.name.upper())
            node = node.parent
        return tuple(names)


class DataItems(list[Item]):
    """A list of items with small lookup helpers."""

    def matches(self, name: str, qualifiers: Sequence[str] = ()) -> list[Item]:
        return resolve_all(self, name, qualifiers)

    def find(self, name: str, qualifiers: Sequence[str] = ()) -> Item | None:
        return find_item(self, name, qualifiers)


class DataDivision(DataItems):
    """The parsed DATA DIVISION, usable as a list and as an object with .items."""

    @property
    def items(self) -> list[Item]:
        return list(self)


def resolve_all(items: Iterable[Item], name: str, qualifiers: Sequence[str] = ()) -> list[Item]:
    """All items matching name and, in order, the supplied ancestor qualifiers."""

    target = name.upper()
    matches = [item for item in items if item.name.upper() == target]
    wanted = [qualifier.upper() for qualifier in qualifiers]
    if not wanted:
        return matches

    found: list[Item] = []
    for item in matches:
        chain = list(item.qualifiers)
        position = 0
        possible = True
        for qualifier in wanted:
            try:
                position = chain.index(qualifier, position) + 1
            except ValueError:
                possible = False
                break
        if possible:
            found.append(item)
    return found


def find_item(items: Iterable[Item], name: str, qualifiers: Sequence[str] = ()) -> Item | None:
    """The unique matching item, or None for zero or several matches."""

    matches = resolve_all(items, name, qualifiers)
    return matches[0] if len(matches) == 1 else None


def _data_bounds(tokens: Sequence[Token]) -> tuple[int, int]:
    start = 0
    end = len(tokens)
    for i in range(len(tokens) - 1):
        if tokens[i].kind == "word" and tokens[i].text == "DATA" and tokens[i + 1].text == "DIVISION":
            start = i + 2
            break
    for i in range(start, len(tokens) - 1):
        if tokens[i].kind == "word" and tokens[i].text == "PROCEDURE" and tokens[i + 1].text == "DIVISION":
            end = i
            break
    return start, end


def _level_of(token: Token) -> int | None:
    if token.kind != "num" or not token.text.isdigit():
        return None
    level = int(token.text)
    if 1 <= level <= 49 or level == 77 or level in (66, 88):
        return level
    return None


def _entry_end(tokens: Sequence[Token], start: int, end: int) -> int:
    position = start + 1
    while position < end and not (tokens[position].kind == "sep" and tokens[position].text == "."):
        position += 1
    return position


_USAGE = {
    "BINARY": "COMP",
    "COMP": "COMP",
    "COMP-4": "COMP",
    "COMPUTATIONAL": "COMP",
    "COMPUTATIONAL-4": "COMP",
    "COMP-3": "COMP-3",
    "COMPUTATIONAL-3": "COMP-3",
    "PACKED-DECIMAL": "COMP-3",
    "COMP-5": "COMP-5",
    "COMPUTATIONAL-5": "COMP-5",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-2": "COMP-2",
    "DISPLAY": "DISPLAY",
    "INDEX": "INDEX",
    "POINTER": "POINTER",
}

_CLAUSE_WORDS = {
    "BLANK",
    "EXTERNAL",
    "GLOBAL",
    "INDEXED",
    "JUST",
    "JUSTIFIED",
    "KEY",
    "OCCURS",
    "PIC",
    "PICTURE",
    "REDEFINES",
    "RENAMES",
    "SIGN",
    "SYNC",
    "SYNCHRONIZED",
    "TYPE",
    "TYPEDEF",
    "USAGE",
    "VALUE",
    "VALUES",
}


def _explicit_usage(entry: Sequence[Token]) -> str | None:
    for token in entry[2:]:
        if token.kind == "word" and token.text in _USAGE:
            return _USAGE[token.text]
    return None


def _index_names(entry: Sequence[Token]) -> list[str]:
    names: list[str] = []
    for i, token in enumerate(entry):
        if token.kind != "word" or token.text != "INDEXED":
            continue
        if i + 2 >= len(entry) or entry[i + 1].kind != "word" or entry[i + 1].text != "BY":
            continue
        position = i + 2
        while position < len(entry) and entry[position].kind == "word":
            name = entry[position].text
            if name in _CLAUSE_WORDS:
                break
            names.append(name)
            position += 1
    return names


def _item_from_entry(entry: Sequence[Token], parent: Item | None, inherited: str, level: int) -> Item:
    picture = None
    for token in entry[2:]:
        if token.kind == "pic":
            picture = parse_pic(token.text)
            break
    usage = _explicit_usage(entry) or inherited
    return Item(
        name=entry[1].text,
        level=level,
        pic=picture,
        usage=usage,
        parent=parent,
        index=usage == "INDEX",
        file=entry[0].file,
        line=entry[0].line,
    )


def data_items(tokens: Sequence[Token]) -> DataItems:
    """Extract levels 01-49 and 77 from the DATA DIVISION, with INDEXED BY names."""

    source = list(tokens)
    start, end = _data_bounds(source)
    items = DataItems()
    stack: list[Item] = []
    i = start
    while i < end:
        level = _level_of(source[i])
        if level is None:
            i += 1
            continue

        stop = _entry_end(source, i, end)
        entry = source[i:stop]
        i = stop + 1 if stop < end else end

        if level in (66, 88):
            continue
        if len(entry) < 2 or entry[1].kind != "word":
            continue

        if level == 77:
            parent = None
            stack.clear()
        else:
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None

        inherited = parent.usage if parent is not None else "DISPLAY"
        item = _item_from_entry(entry, parent, inherited, level)
        items.append(item)
        if parent is not None:
            parent.children.append(item)
        if level != 77:
            stack.append(item)

        for name in _index_names(entry):
            index_item = Item(
                name=name,
                level=level,
                pic=None,
                usage="INDEX",
                parent=parent,
                index=True,
                file=entry[0].file,
                line=entry[0].line,
            )
            items.append(index_item)
            if parent is not None:
                parent.children.append(index_item)

    return items


def parse_data(tokens: Sequence[Token]) -> DataDivision:
    return DataDivision(data_items(tokens))


DataItem = Item
items_from_tokens = data_items
lookup = find_item
parse_data_items = data_items
parse_items = data_items
resolve = find_item
