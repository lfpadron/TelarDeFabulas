from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.utils.translation import gettext as _
from ebooklib import epub

from apps.manuscripts.models import ManuscriptNode

from .services import css_font_name, css_number, ordered_export_nodes, render_content_blocks


HEADING_TAGS = {
    ManuscriptNode.NodeType.BOOK: "h1",
    ManuscriptNode.NodeType.PART: "h2",
    ManuscriptNode.NodeType.CHAPTER: "h2",
    ManuscriptNode.NodeType.SCENE: "h3",
    ManuscriptNode.NodeType.FRAGMENT: "h4",
}


def creator_for_user(user):
    return getattr(user, "display_alias", "") or getattr(user, "name", "") or getattr(user, "email", "")


def epub_title(export_job):
    if export_job.root_node_id:
        return export_job.root_node.title
    return export_job.project.name


def epub_language(project):
    return project.locale or project.language or "es-mx"


def build_epub_css(style):
    text_alignment = style.text_alignment.lower().replace("_", "-")
    fallback_family = "serif" if style.font_category == style.FontCategory.SERIF else "sans-serif"
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
    tag = HEADING_TAGS.get(node.node_type, "h2")
    content_html = render_content_blocks(node.content)
    separator = ""
    if node.node_type == ManuscriptNode.NodeType.SCENE and style_template.scene_separator:
        separator = f'<div class="scene-separator">{escape(style_template.scene_separator)}</div>'

    return f"""
<section id="node-{node.id}" class="node node-{node.node_type.lower()}">
  <{tag}>{escape(node.title)}</{tag}>
  {content_html}
  {separator}
</section>
"""


def build_chapter_content(export_job, node):
    return f"""<html>
  <head>
    <title>{escape(node.title)}</title>
  </head>
  <body>
    {render_epub_node(node, export_job.style_template)}
  </body>
</html>
"""


def build_export_epub(export_job):
    book = epub.EpubBook()
    title = epub_title(export_job)
    language = epub_language(export_job.project)
    nodes = ordered_export_nodes(export_job)

    book.set_identifier(f"telar-export-{export_job.pk}")
    book.set_title(title)
    book.set_language(language)
    creator = creator_for_user(export_job.user)
    if creator:
        book.add_author(creator)
    book.add_metadata("DC", "description", _("Exportación EPUB generada por Telar de Fábulas."))

    style_item = epub.EpubItem(
        uid="telar-style",
        file_name="style.css",
        media_type="text/css",
        content=build_epub_css(export_job.style_template).encode("utf-8"),
    )
    book.add_item(style_item)

    chapters = []
    for node in nodes:
        chapter = epub.EpubHtml(
            title=node.title,
            file_name=f"node-{node.id}.xhtml",
            lang=language,
            uid=f"node-{node.id}",
        )
        chapter.content = build_chapter_content(export_job, node)
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
