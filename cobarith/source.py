"""Fixed-format COBOL source tokenizing and COPY expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Token", "Library", "source_tokens", "tokenize_file"]

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
NUM_RE = re.compile(r"(?:\d*\.\d+|\d+)(?![A-Za-z0-9-])")


@dataclass(frozen=True)
class Token:
    """One lexical token. ``col`` and ``end`` are 0-based offsets in the code area."""

    text: str
    kind: str
    file: str
    line: int
    col: int
    end: int


class Library:
    """Copybook lookup by upper-cased stem, preferring the closest path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.missing: set[str] = set()
        self._by_name: dict[str, list[Path]] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in (".cpy", ".dcl"):
                self._by_name.setdefault(path.stem.upper(), []).append(path)

    def find(self, name: str, including: str | Path) -> Path | None:
        key = name.upper()
        candidates = self._by_name.get(key)
        if not candidates:
            self.missing.add(key)
            return None

        inc = Path(including).resolve()

        def common_prefix(path: Path) -> int:
            a = path.resolve().parts
            b = inc.parts
            i = 0
            while i < len(a) and i < len(b) and a[i] == b[i]:
                i += 1
            return i

        return max(candidates, key=lambda p: (common_prefix(p), str(p)))


def _open_literal(text: str) -> bool:
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif ch in "'\"":
            quote = ch
        i += 1
    return quote is not None


def _logical_lines(raw: str) -> tuple[str, list[tuple[int, int]]]:
    chars: list[str] = []
    pos: list[tuple[int, int]] = []
    last_line = 0
    last_seg_len = 0

    def add_text(text: str, line: int, start_col: int) -> None:
        chars.extend(text)
        pos.extend((line, start_col + k) for k in range(len(text)))

    for lineno, raw_line in enumerate(raw.splitlines(), 1):
        indicator = raw_line[6] if len(raw_line) > 6 else " "
        if indicator in "*/" or indicator in "Dd":
            continue

        code = raw_line[7:72].ljust(65)
        if indicator != "-":
            if chars:
                chars.append("\n")
                pos.append((lineno, 0))
            add_text(code, lineno, 0)
            last_line = lineno
            last_seg_len = 65
            continue

        stripped = code.strip()
        if not stripped:
            last_line = lineno
            last_seg_len = 0
            continue

        lstrip_len = len(code) - len(code.lstrip())
        if _open_literal("".join(chars)):
            if stripped[0] in "'\"":
                while last_seg_len < 65:
                    chars.append(" ")
                    pos.append((last_line, last_seg_len))
                    last_seg_len += 1
                content = code[lstrip_len + 1 :]
                add_text(content, lineno, lstrip_len + 1)
                last_line = lineno
                last_seg_len = len(content)
            else:
                content = stripped
                add_text(content, lineno, lstrip_len)
                last_line = lineno
                last_seg_len = len(content)
        else:
            while chars and chars[-1] == " ":
                chars.pop()
                pos.pop()
            content = stripped
            add_text(content, lineno, lstrip_len)
            last_line = lineno
            last_seg_len = len(content)

    return "".join(chars), pos


def _capture_pic(text: str, start: int) -> int:
    n = len(text)
    j = start
    while j < n and not text[j].isspace():
        ch = text[j]
        if ch == ".":
            if j + 1 < n and text[j + 1].isdigit():
                j += 1
                continue
            break
        if ch == ";":
            break
        j += 1
    return j


def _scan(text: str, pos: list[tuple[int, int]], file: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    expect_pic = False

    def make(kind: str, start: int, end: int) -> Token:
        line, col = pos[start]
        return Token(text[start:end], kind, file, line, col, col + (end - start))

    while i < n:
        ch = text[i]
        if ch.isspace() or ch in ",;":
            i += 1
            continue

        if expect_pic:
            if ch.isalpha():
                m = WORD_RE.match(text, i)
                if m and m.group(0).upper() == "IS":
                    i = m.end()
                    continue
            j = _capture_pic(text, i)
            if j > i:
                tokens.append(make("pic", i, j))
                i = j
                expect_pic = False
                continue
            expect_pic = False

        if text.startswith("==", i):
            j = text.find("==", i + 2)
            j = n if j == -1 else j + 2
            tokens.append(make("pseudo", i, j))
            i = j
            continue

        prefix = 0
        if ch in "XNZGxnzg" and i + 1 < n and text[i + 1] in "'\"":
            prefix = 1
        qpos = i + prefix
        if qpos < n and text[qpos] in "'\"":
            quote = text[qpos]
            k = qpos + 1
            while k < n:
                if text[k] == quote:
                    if k + 1 < n and text[k + 1] == quote:
                        k += 2
                        continue
                    k += 1
                    break
                k += 1
            tokens.append(make("lit", i, k))
            i = k
            continue

        m = NUM_RE.match(text, i)
        if m:
            j = m.end()
            tokens.append(make("num", i, j))
            i = j
            continue

        m = WORD_RE.match(text, i)
        if m and any(c.isalpha() for c in m.group(0)):
            j = m.end()
            word = text[i:j].upper()
            line, col = pos[i]
            tokens.append(Token(word, "word", file, line, col, col + (j - i)))
            if word in ("PIC", "PICTURE"):
                expect_pic = True
            i = j
            continue

        two = text[i : i + 2]
        if two in ("**", ">=", "<="):
            tokens.append(make("sep", i, i + 2))
            i += 2
            continue
        if ch in "().:=+-*/<>&":
            tokens.append(make("sep", i, i + 1))
            i += 1
            continue

        tokens.append(make("sep", i, i + 1))
        i += 1

    return tokens


def _tokenize_text(raw: str, file: str) -> list[Token]:
    text, pos = _logical_lines(raw)
    return _scan(text, pos, file)


def tokenize_file(path: str | Path) -> list[Token]:
    path = Path(path)
    return _tokenize_text(path.read_text(encoding="utf-8", errors="replace"), path.name)


def _literal_value(text: str) -> str:
    if len(text) >= 2 and text[0] in "XNZGxnzg" and text[1] in "'\"":
        text = text[1:]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        quote = text[0]
        return text[1:-1].replace(quote + quote, quote)
    return text


def _copy_name(token: Token) -> str | None:
    if token.kind == "word":
        return token.text.upper()
    if token.kind == "lit":
        return _literal_value(token.text).upper()
    return None


def _pseudo_inner(text: str) -> str:
    if len(text) >= 4 and text.startswith("==") and text.endswith("=="):
        return text[2:-2]
    return text


def _apply_replacement(text: str, source: Token, target: Token) -> str:
    replacement = _pseudo_inner(target.text) if target.kind == "pseudo" else target.text
    if source.kind == "pseudo":
        pattern = re.escape(_pseudo_inner(source.text))
        return re.sub(pattern, lambda _m: replacement, text, flags=re.IGNORECASE)

    pattern = re.escape(source.text)
    pattern = r"(?<![A-Za-z0-9-])" + pattern + r"(?![A-Za-z0-9-])"
    return re.sub(pattern, lambda _m: replacement, text, flags=re.IGNORECASE)


def _expand_tokens(tokens: list[Token], library: Library, including: Path, depth: int) -> list[Token]:
    if depth >= 10:
        return tokens

    out: list[Token] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.kind == "word" and token.text == "COPY":
            if i + 1 >= len(tokens):
                out.append(token)
                i += 1
                continue

            name = _copy_name(tokens[i + 1])
            j = i + 2
            pairs: list[tuple[Token, Token]] = []
            if j < len(tokens) and tokens[j].kind == "word" and tokens[j].text == "REPLACING":
                j += 1
                while j < len(tokens) and not (tokens[j].kind == "sep" and tokens[j].text == "."):
                    if j + 2 >= len(tokens):
                        break
                    source, by, target = tokens[j], tokens[j + 1], tokens[j + 2]
                    if by.kind == "word" and by.text == "BY":
                        pairs.append((source, target))
                        j += 3
                    else:
                        j += 1
            if j < len(tokens) and tokens[j].kind == "sep" and tokens[j].text == ".":
                j += 1

            if name:
                member = library.find(name, including)
                if member is not None:
                    member_text = member.read_text(encoding="utf-8", errors="replace")
                    for source, target in pairs:
                        member_text = _apply_replacement(member_text, source, target)
                    member_tokens = _tokenize_text(member_text, member.name)
                    out.extend(_expand_tokens(member_tokens, library, member, depth + 1))
            i = j
            continue

        if (
            token.kind == "word"
            and token.text == "EXEC"
            and i + 3 < len(tokens)
            and tokens[i + 1].kind == "word"
            and tokens[i + 1].text == "SQL"
            and tokens[i + 2].kind == "word"
            and tokens[i + 2].text == "INCLUDE"
        ):
            name = _copy_name(tokens[i + 3])
            k = i + 4
            while k < len(tokens) and not (tokens[k].kind == "word" and tokens[k].text == "END-EXEC"):
                k += 1
            end = k + 1 if k < len(tokens) else k

            if name:
                member = library.find(name, including)
                if member is not None:
                    out.extend(_source_tokens(member, library, depth + 1))
            i = end
            continue

        out.append(token)
        i += 1

    return out


def _source_tokens(path: Path, library: Library, depth: int) -> list[Token]:
    return _expand_tokens(tokenize_file(path), library, path, depth)


def source_tokens(path: str | Path, library: Library) -> list[Token]:
    """Tokenize *path* with COPY and EXEC SQL INCLUDE expanded."""

    return _source_tokens(Path(path), library, 0)
