"""HTML -> PDF with WeasyPrint (optional dependency: pip install isitmyisp[pdf])."""

from __future__ import annotations


class PdfUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception:  # ImportError, or OSError when pango is missing
        return False
    return True


def html_to_pdf(html: str) -> bytes:
    try:
        import weasyprint
    except Exception as exc:
        raise PdfUnavailable("PDF export needs WeasyPrint: pip install 'isitmyisp[pdf]' "
                             "(the Docker image already includes it). You can also print the HTML report "
                             "to PDF from any browser.") from exc
    return weasyprint.HTML(string=html).write_pdf()
