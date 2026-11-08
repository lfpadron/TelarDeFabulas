from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.utils.translation import gettext as _
from ebooklib import epub

from apps.manuscripts.models import ManuscriptNode

from .services import css_alignment, css_font_name, css_number, heading_level, render_content_blocks, selected_content
from .snapshots import get_export_document


def build_epub_css(style):
    text_alignment = css_alignment(style)
    fallback_family = "serif" if style.font_category == "SERIF" else "sans-serif"
    return f"""
body {{
  font-family: '{css_font_name(style.font_body)}', {fallback_family};
  font-size: {css_number(style.body_size)}pt;
  line-height: {css_number(style.line_spacing)};
  text-align: {text_alignment};
}}
h1, h2, h3, h4 {{
  font-family: '{css_font_name(style.font_heading)}', {fallback_family};
  font-size: {css_number(style.heading_size)}pt;
  line-height: 1.2;
  margin: 1.4em 0 0.7em;
  text-align: left;
}}
p {{
  margin: 0 0 {css_number(style.paragraph_spacing)}pt;
  text-indent: {css_number(style.first_line_indent)}mm;
}}
.scene-separator {{
  margin: 2em 0;
  text-align: center;
  text-indent: 0;
}}
""".strip()


def render_epub_node(node, style_template):
    tag = f"h{heading_level(node)}"
    content_html = render_content_blocks(selected_content(node))
    separator = ""
    if node.node_type == ManuscriptNode.NodeType.SCENE and style_template.scene_separator:
        separator = f'<div class="scene-separator">{escape(style_template.scene_separator)}</div>'

    return f"""
<section id="node-{node.id}" class="node node-{escape(node.node_type.lower())}">
  <{tag}>{escape(node.display_title)}</{tag}>
  {content_html}
  {separator}
</section>
"""


def build_chapter_content(node, style_template):
    return f"""<html>
  <head>
    <title>{escape(node.display_title)}</title>
  </head>
  <body>
    {render_epub_node(node, style_template)}
  </body>
</html>
"""


def build_export_epub(export_job, *, document=None):
    document = document or get_export_document(export_job)
    book = epub.EpubBook()
    title = document.title
    language = document.locale
    nodes = document.nodes

    book.set_identifier(f"telar-export-{export_job.pk}")
    book.set_title(title)
    book.set_language(language)
    creator = document.creator
    if creator:
        book.add_author(creator)
    book.add_metadata("DC", "description", _("Exportación EPUB generada por Telar de Fábulas."))

    style_item = epub.EpubItem(
        uid="telar-style",
        file_name="style.css",
        media_type="text/css",
        content=build_epub_css(document.style).encode("utf-8"),
    )
    book.add_item(style_item)

    chapters = []
    for node in nodes:
        chapter = epub.EpubHtml(
            title=node.display_title,
            file_name=f"node-{node.id}.xhtml",
            lang=language,
            uid=f"node-{node.id}",
        )
        chapter.content = build_chapter_content(node, document.style)
        chapter.add_item(style_item)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    with NamedTemporaryFile(suffix=".epub", delete=False) as output:
        output_path = Path(output.name)

    try:
        epub.write_epub(str(output_path), book, {})
        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)
