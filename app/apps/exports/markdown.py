import re

from .services import heading_level
from .snapshots import get_export_document


def escape_prose(text):
    # CommonMark punctuation escaping keeps plain prose (including raw HTML) inert.
    escaped = re.sub(r"([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\\\1", text)
    # Preserve indentation without turning indented literary text into code blocks.
    return re.sub(r"(?m)^( {4,}| *\t[ \t]*)", lambda match: "".join(
        "&#9;" if char == "\t" else "&#32;" for char in match[0]), escaped)


def build_export_markdown(export_job, *, document=None):
    document = document if document is not None else get_export_document(export_job)
    blocks = []
    for node in document.nodes:
        title = " ".join(node.title.splitlines())
        blocks.append(f"{'#' * heading_level(node)} {escape_prose(title)}")
        if node.export_content:
            blocks.append(escape_prose(node.export_content.replace("\r\n", "\n").replace("\r", "\n")))
    return "\n\n".join(blocks) + "\n"
