from html import escape
from unittest.mock import patch

from django.test import override_settings

from apps.exports.epub import build_epub_css, render_epub_node
from apps.exports.pdf import build_export_pdf, reject_external_resource
from apps.exports.services import build_export_html, css_number
from apps.exports.tasks import generate_export_job
from apps.manuscripts.models import ManuscriptNode

from .helpers import SecurityTestCase


class RenderingSecurityTests(SecurityTestCase):
    payload = '<script>alert("private")</script><img src="https://example.test/track" onerror="alert(1)">'

    def test_manuscript_detail_escapes_user_html(self):
        ManuscriptNode.objects.filter(pk=self.scene.pk).update(content=self.payload)
        response = self.client.get(self.url("manuscripts:detail", node_pk=self.scene.pk))
        self.assertNotContains(response, self.payload)
        self.assertContains(response, "&lt;script&gt;")

    def test_export_escapes_title_content_and_scene_separator(self):
        self.scene.content = self.payload
        self.scene.title = self.payload
        self.scene.save()
        self.job.style_template.scene_separator = self.payload
        html = build_export_html(self.job)
        self.assertNotIn(self.payload, html)
        self.assertIn(escape(self.payload), html)
        self.assertIn('http-equiv="Content-Security-Policy"', html)
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("<script>", html)

    @override_settings(EXPORT_PREVIEW_MAX_NODES=2, EXPORT_PREVIEW_MAX_WORDS=2)
    def test_preview_stays_sandboxed_and_limited(self):
        ManuscriptNode.objects.filter(pk=self.book.pk).update(content=self.payload)
        response = self.client.get(self.url("exports:preview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sandbox=""')
        self.assertNotContains(response, self.payload)
        result = response.context["preview_result"]
        self.assertTrue(result.truncated)
        self.assertLessEqual(result.node_count, 2)
        self.assertLessEqual(result.word_count, 2)

    def test_css_fields_cannot_inject_resources_or_close_style_tag(self):
        style = self.job.style_template
        style.font_body = "x';} @import url(https://example.test/); /*"
        style.font_heading = "</style><script>alert(1)</script>"
        style.text_alignment = "left; background: url(file:///etc/passwd)"
        style.margin_top = "0; background: url(https://example.test/)"
        for output in (build_export_html(self.job), build_epub_css(style)):
            self.assertNotIn("@import", output)
            self.assertNotIn("url(", output)
            self.assertNotIn("<script>", output)
            self.assertIn("text-align: left;", output)

    def test_css_numbers_preserve_tens_and_reject_invalid_values(self):
        for value, expected in ((10, "10"), (20, "20"), ("1.50", "1.5"), ("NaN", "0"), ("Infinity", "0"), ("bad;", "0"), (-1, "0")):
            with self.subTest(value=value):
                self.assertEqual(css_number(value), expected)

    def test_epub_content_does_not_create_executable_elements(self):
        self.scene.content = self.payload
        self.scene.title = self.payload
        rendered = render_epub_node(self.scene, self.style)
        self.assertIn(escape(self.payload), rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)

    def test_pdf_renderer_does_not_fetch_network_or_local_resources(self):
        for url in ("file:///etc/passwd", "http://localhost/private", "https://example.test/", "data:text/html,script"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                reject_external_resource(url)
        with patch("weasyprint.HTML") as renderer:
            build_export_pdf(self.job)
        self.assertIs(renderer.call_args.kwargs["url_fetcher"], reject_external_resource)
        self.assertNotIn("base_url", renderer.call_args.kwargs)

    def test_worker_error_message_does_not_expose_internal_paths(self):
        with patch("apps.exports.tasks.build_export_html", side_effect=OSError("/private/path/credentials")):
            generate_export_job.run(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        self.assertNotIn("/private/", self.job.error_message)
