from html import escape

from django.utils.translation import gettext as _

from apps.manuscripts.models import ManuscriptNode


HEADING_TAGS = {
    ManuscriptNode.NodeType.BOOK: "h1",
    ManuscriptNode.NodeType.PART: "h2",
    ManuscriptNode.NodeType.CHAPTER: "h2",
    ManuscriptNode.NodeType.SCENE: "h3",
    ManuscriptNode.NodeType.FRAGMENT: "h4",
}


def css_font_name(font_name):
    return escape(str(font_name).replace("\\", "").replace("'", "\\'"))


def css_number(value):
    return str(value).rstrip("0").rstrip(".")


def ordered_export_nodes(export_job):
    nodes = list(
        ManuscriptNode.objects.filter(project=export_job.project)
        .select_related("parent")
        .order_by("parent_id", "position", "created_at")
    )
    nodes_by_id = {node.id: node for node in nodes}
    children_by_parent = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    ordered = []

    def visit(node):
        ordered.append(node)
        for child in children_by_parent.get(node.id, []):
            visit(child)

    if export_job.root_node_id:
        root = nodes_by_id.get(export_job.root_node_id)
        if root:
            visit(root)
    else:
        for root in children_by_parent.get(None, []):
            visit(root)

    return ordered


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
        f'<li class="toc-item toc-{escape(node.node_type.lower())}"><a href="#node-{node.id}">{escape(node.title)}</a></li>'
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


def render_node(node, style_template):
    tag = HEADING_TAGS.get(node.node_type, "h2")
    content_html = render_content_blocks(node.content)
    separator = ""
    if node.node_type == ManuscriptNode.NodeType.SCENE and style_template.scene_separator:
        separator = f'<div class="scene-separator">{escape(style_template.scene_separator)}</div>'

    return f"""
<section class="node node-{escape(node.node_type.lower())}" id="node-{node.id}">
  <{tag}>{escape(node.title)}</{tag}>
  {content_html}
  {separator}
</section>
"""


def build_export_html(export_job):
    project = export_job.project
    style = export_job.style_template
    nodes = ordered_export_nodes(export_job)
    title = export_job.root_node.title if export_job.root_node_id else project.name
    lang = project.locale or "es-mx"
    text_alignment = style.text_alignment.lower().replace("_", "-")
    fallback_family = "serif" if style.font_category == style.FontCategory.SERIF else "sans-serif"

    toc = render_toc(nodes) if style.include_table_of_contents else ""
    body = "\n".join(render_node(node, style) for node in nodes)

    return f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
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
  </style>
</head>
<body>
  <main>
    {toc}
    {body}
  </main>
</body>
</html>
"""
