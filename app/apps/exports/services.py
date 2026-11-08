from dataclasses import dataclass
from html import escape
from decimal import Decimal, InvalidOperation
import re

from django.utils.translation import gettext as _

from apps.manuscripts.models import WORD_RE, ManuscriptNode, count_words
from apps.manuscripts.hierarchy import ordered_tree


HEADING_TAGS = {
    ManuscriptNode.NodeType.BOOK: "h1",
    ManuscriptNode.NodeType.PART: "h2",
    ManuscriptNode.NodeType.CHAPTER: "h2",
    ManuscriptNode.NodeType.SCENE: "h3",
    ManuscriptNode.NodeType.FRAGMENT: "h4",
}


@dataclass(frozen=True)
class ExportRenderNode:
    node: ManuscriptNode
    content: str


@dataclass(frozen=True)
class ExportHtmlRenderResult:
    html: str
    truncated: bool
    node_count: int
    word_count: int


def css_font_name(font_name):
    # A font family is data, never CSS syntax or a resource URL.
    return re.sub(r"[^\w -]", "", str(font_name), flags=re.UNICODE)[:120] or "serif"


def css_number(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return "0"
    return format(number.normalize(), "f") if number.is_finite() and number >= 0 else "0"


def css_alignment(style):
    return style.text_alignment.lower() if style.text_alignment in {"LEFT", "RIGHT", "CENTER", "JUSTIFY"} else "left"


def ordered_project_nodes(project, root_node=None):
    nodes = list(
        ManuscriptNode.objects.filter(project=project)
        .order_by("position", "created_at", "pk")
    )
    nodes_by_id = {node.id: node for node in nodes}
    children_by_parent = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    if root_node:
        root = nodes_by_id.get(root_node.id)
        if root is None:
            return []
        included, pending = set(), [root]
        while pending:
            node = pending.pop()
            if node.pk in included:
                continue
            included.add(node.pk)
            pending.extend(children_by_parent.get(node.pk, ()))
        nodes = [node for node in nodes if node.pk in included]
    ordered = []
    for node, depth in ordered_tree(nodes):
        node.export_depth = depth
        ordered.append(node)
    return ordered


def heading_level(node):
    default = int(HEADING_TAGS.get(node.node_type, "h2")[1])
    return min(6, getattr(node, "export_depth", default - 1) + 1)


def ordered_export_nodes(export_job):
    root_node = export_job.root_node if export_job.root_node_id else None
    return ordered_project_nodes(export_job.project, root_node)


def truncate_content_to_words(content, max_words):
    content = content or ""
    if max_words is None:
        return content, count_words(content), False

    matches = list(WORD_RE.finditer(content))
    if len(matches) <= max_words:
        return content, len(matches), False

    if max_words <= 0:
        return "", 0, bool(matches)

    cutoff = matches[max_words - 1].end()
    return f"{content[:cutoff].rstrip()}...", max_words, True


def limited_render_nodes(nodes, max_nodes=None, max_words=None):
    render_nodes = []
    truncated = False
    word_count = 0

    for node in nodes:
        if max_nodes is not None and len(render_nodes) >= max_nodes:
            truncated = True
            break

        remaining_words = None
        if max_words is not None:
            remaining_words = max_words - word_count
            if remaining_words <= 0:
                truncated = True
                break

        content, used_words, content_truncated = truncate_content_to_words(node.content, remaining_words)
        render_nodes.append(ExportRenderNode(node=node, content=content))
        word_count += used_words

        if content_truncated:
            truncated = True
            break

    return render_nodes, truncated, word_count


def render_content_blocks(content):
    blocks = [block.strip() for block in (content or "").split("\n\n") if block.strip()]
    rendered = []
    for block in blocks:
        lines = [escape(line) for line in block.splitlines()]
        rendered.append(f"<p>{'<br>'.join(lines)}</p>")
    return "\n".join(rendered)


def render_toc(nodes):
    if not nodes:
        return ""

    items = "\n".join(
        f'<li class="toc-item toc-{escape(node.node_type.lower())}"><a href="#node-{node.id}">{escape(node.display_title)}</a></li>'
        for node in nodes
    )
    return f"""
<nav class="toc" aria-label="{escape(_('Índice'))}">
  <h2>{escape(_('Índice'))}</h2>
  <ol>
    {items}
  </ol>
</nav>
"""


def render_node(node, style_template, content=None):
    tag = f"h{heading_level(node)}"
    content_html = render_content_blocks(node.content if content is None else content)
    separator = ""
    if node.node_type == ManuscriptNode.NodeType.SCENE and style_template.scene_separator:
        separator = f'<div class="scene-separator">{escape(style_template.scene_separator)}</div>'

    return f"""
<section class="node node-{escape(node.node_type.lower())}" id="node-{node.id}">
  <{tag}>{escape(node.display_title)}</{tag}>
  {content_html}
  {separator}
</section>
"""


def render_export_html(
    project,
    style_template,
    root_node=None,
    max_nodes=None,
    max_words=None,
    preview_mode=False,
):
    style = style_template
    nodes = ordered_project_nodes(project, root_node)
    render_nodes, truncated, word_count = limited_render_nodes(nodes, max_nodes, max_words)
    title = root_node.display_title if root_node else project.name
    lang = project.locale or "es-mx"
    text_alignment = css_alignment(style)
    fallback_family = "serif" if style.font_category == style.FontCategory.SERIF else "sans-serif"
    page_number_css = ""
    if style.include_page_numbers:
        page_number_css = f"""
      @bottom-center {{
        content: counter(page);
        font-family: '{css_font_name(style.font_body)}', {fallback_family};
        font-size: 9pt;
        color: #666666;
      }}
"""

    toc_nodes = [render_node_item.node for render_node_item in render_nodes]
    toc = render_toc(toc_nodes) if style.include_table_of_contents else ""
    preview_notice = ""
    if preview_mode and truncated:
        preview_notice = (
            '<p class="preview-limited-notice">'
            f"{escape(_('Vista previa limitada. Exporta el archivo completo para ver todo el manuscrito.'))}"
            "</p>"
        )
    body = "\n".join(
        render_node(render_node_item.node, style, render_node_item.content) for render_node_item in render_nodes
    )

    html = f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
  <title>{escape(title)}</title>
  <style>
    @page {{
      margin: {css_number(style.margin_top)}mm {css_number(style.margin_right)}mm {css_number(style.margin_bottom)}mm {css_number(style.margin_left)}mm;
      {page_number_css}
    }}
    @media print {{
      body {{
        margin: 0;
      }}
    }}
    body {{
      box-sizing: border-box;
      font-family: '{css_font_name(style.font_body)}', {fallback_family};
      font-size: {css_number(style.body_size)}pt;
      line-height: {css_number(style.line_spacing)};
      margin: {css_number(style.margin_top)}mm {css_number(style.margin_right)}mm {css_number(style.margin_bottom)}mm {css_number(style.margin_left)}mm;
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
    .toc {{
      border-bottom: 1px solid #d0d0d0;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
    }}
    .toc a {{
      color: inherit;
    }}
    .scene-separator {{
      margin: 2rem 0;
      text-align: center;
    }}
    .preview-limited-notice {{
      background: #fff4d8;
      border: 1px solid #e2b34b;
      border-radius: 6px;
      color: #17202a;
      margin: 0 0 1.5rem;
      padding: 0.75rem;
      text-indent: 0;
    }}
  </style>
</head>
<body>
  <main>
    {preview_notice}
    {toc}
    {body}
  </main>
</body>
</html>
"""
    return ExportHtmlRenderResult(
        html=html,
        truncated=truncated,
        node_count=len(render_nodes),
        word_count=word_count,
    )


def build_export_html(export_job):
    root_node = export_job.root_node if export_job.root_node_id else None
    return render_export_html(
        project=export_job.project,
        root_node=root_node,
        style_template=export_job.style_template,
    ).html
