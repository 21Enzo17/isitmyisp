"""A form that comes back with an error keeps what was typed in it.

The settings pages draw every form from the saved settings, so after a rejected POST the fields would
show the old values and what you typed would be gone. Rather than teach each of the ~70 inputs where
to look, the page is drawn as usual and then the form that was sent (the one whose action is the
request path) gets the sent values back: text and number fields, text areas, check boxes and
selects. Hidden fields (the CSRF token, ids) and passwords are left as drawn.
"""

from __future__ import annotations

import re
from collections import defaultdict

from markupsafe import escape

_FORM = re.compile(r"<form\b[^>]*>.*?</form>", re.DOTALL | re.IGNORECASE)
_ACTION = re.compile(r"""\baction\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_FIELD = re.compile(r"<input\b[^>]*>|<textarea\b[^>]*>.*?</textarea>|<select\b[^>]*>.*?</select>", re.DOTALL | re.IGNORECASE)
_OPTION = re.compile(r"<option\b[^>]*>", re.IGNORECASE)
SKIP = {"hidden", "password", "submit", "button", "reset", "file", "image"}


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf"""\s{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.IGNORECASE)
    if not m:
        return None
    from html import unescape
    return unescape(next(v for v in m.groups() if v is not None))


def _set_flag(tag: str, flag: str, on: bool) -> str:
    tag = re.sub(rf"""\s{flag}(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?(?=[\s/>])""", "", tag, flags=re.IGNORECASE)
    return re.sub(r"\s*(/?>)$", rf" {flag}\1", tag) if on else tag


def _set_value(tag: str, value: str) -> str:
    v = f' value="{escape(value)}"'
    if re.search(r"""\svalue\s*=""", tag, re.IGNORECASE):
        return re.sub(r"""\svalue\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", lambda _: v, tag, count=1, flags=re.IGNORECASE)
    return re.sub(r"\s*(/?>)$", lambda m: v + m.group(1), tag)


def _refill_form(html: str, form) -> str:
    seen: dict[str, int] = defaultdict(int)

    def field(m: re.Match) -> str:
        text = m.group(0)
        head = text[: text.index(">") + 1]
        name = _attr(head, "name")
        if not name:
            return text
        sent = form.getlist(name)
        low = head[:9].lower()
        if low.startswith("<textarea"):
            i = seen[name]
            seen[name] += 1
            return head + str(escape(sent[i])) + "</textarea>" if i < len(sent) else text
        if low.startswith("<select"):
            if name not in form:            # not sent (disabled): left as drawn
                return text
            return _OPTION.sub(lambda o: _set_flag(o.group(0), "selected", _attr(o.group(0), "value") in sent)
                               if _attr(o.group(0), "value") is not None else o.group(0), text)
        kind = (_attr(head, "type") or "text").lower()
        if kind in SKIP:
            return text
        if kind in ("checkbox", "radio"):
            return _set_flag(text, "checked", (_attr(text, "value") or "on") in sent)
        i = seen[name]
        seen[name] += 1
        return _set_value(text, sent[i]) if i < len(sent) else text

    return _FIELD.sub(field, html)


def refill(html: str, path: str, form) -> str:
    """`html` with the form posted to `path` showing the values in `form` (a MultiDict)."""
    def one(m: re.Match) -> str:
        a = _ACTION.search(m.group(0)[: m.group(0).index(">") + 1])
        return _refill_form(m.group(0), form) if a and a.group(1).split("?")[0] == path else m.group(0)
    return _FORM.sub(one, html)
