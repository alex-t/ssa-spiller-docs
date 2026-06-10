#!/usr/bin/env python3
"""Convert Markdown with mermaid diagrams to PDF.

Usage: python3 md2pdf.py input.md [output.pdf]

Auto-detects Node.js and puppeteer-core/Chromium from cursor-server extensions.
Embeds mermaid.min.js, katex, highlight.js from the bundled assets in this
same directory — no network access needed at render time.
"""

import sys
import os
import re
import subprocess
import tempfile
import markdown
from pathlib import Path


def find_node():
    base = Path.home() / ".cursor-server" / "bin"
    for node in base.rglob("node"):
        if node.is_file() and os.access(node, os.X_OK):
            return str(node)
    raise FileNotFoundError("Node.js not found in ~/.cursor-server/bin")


def find_puppeteer():
    ext_base = Path.home() / ".cursor-server" / "extensions"
    for pkg in ext_base.rglob("puppeteer-core/package.json"):
        puppeteer_dir = pkg.parent
        for chrome in puppeteer_dir.rglob("chrome"):
            if chrome.is_file() and os.access(chrome, os.X_OK):
                return str(puppeteer_dir), str(chrome)
    raise FileNotFoundError(
        "puppeteer-core/chromium not found in ~/.cursor-server/extensions\n"
        "Install the 'yzane.markdown-pdf' VS Code extension in Cursor, then retry."
    )


def md_to_html(md_path):
    with open(md_path, "r") as f:
        content = f.read()

    # Strip YAML frontmatter
    content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)

    # Convert fenced mermaid blocks to <pre class="mermaid"> for mermaid.init()
    content = re.sub(
        r"```mermaid\s*\n(.*?)```",
        r'<pre class="mermaid">\1</pre>',
        content,
        flags=re.DOTALL,
    )

    md_converter = markdown.Markdown(extensions=["tables", "fenced_code"])
    html_body = md_converter.convert(content)

    # Load bundled assets from the same directory as this script
    tools_dir = Path(__file__).parent

    def read_asset(name):
        p = tools_dir / name
        with open(p, "r", errors="ignore") as f:
            return f.read()

    mermaid_js = read_asset("mermaid.min.js")
    katex_js = read_asset("katex.min.js")
    katex_css = read_asset("katex.min.css")
    auto_render_js = read_asset("auto-render.min.js")
    highlight_js = read_asset("highlight.min.js")
    highlight_css = read_asset("github-highlight.min.css")

    CSS = """
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 900px; margin: 40px auto; padding: 0 20px;
    line-height: 1.6; color: #333; font-size: 14px;
  }
  h1 { border-bottom: 2px solid #ddd; padding-bottom: 10px; font-size: 24px; }
  h2 { border-bottom: 1px solid #eee; padding-bottom: 6px; margin-top: 40px; font-size: 20px; }
  h3 { margin-top: 30px; font-size: 16px; }
  code { background: #f6f8fa; padding: 2px 6px; border-radius: 4px; font-size: 13px;
         font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; }
  pre { background: #f6f8fa; padding: 16px; border-radius: 6px; overflow-x: auto;
        line-height: 1.5; font-size: 13px; border: 1px solid #e1e4e8; }
  pre code { background: none; padding: 0; font-size: 13px; }
  .hljs { background: #f6f8fa; }
  pre.mermaid { background: white; text-align: center;
                page-break-inside: avoid; break-inside: avoid; }
  .mermaid svg { max-height: 700px; width: auto;
                 page-break-inside: avoid; break-inside: avoid; }
  table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  th { background: #f0f0f0; font-weight: 600; }
  tr:nth-child(even) { background: #fafafa; }
  hr { border: none; border-top: 1px solid #eee; margin: 30px 0; }
  ul, ol { padding-left: 24px; }
  li { margin-bottom: 4px; }
  strong { color: #111; }
  blockquote { border-left: 4px solid #ddd; margin: 0; padding-left: 16px; color: #666; }
"""

    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        "<script>" + mermaid_js + "</script>\n"
        "<style>" + katex_css + "</style>\n"
        "<script>" + katex_js + "</script>\n"
        "<script>" + auto_render_js + "</script>\n"
        "<style>" + highlight_css + "</style>\n"
        "<script>" + highlight_js + "</script>\n"
        "<style>" + CSS + "</style>\n"
        "</head>\n<body>\n" + html_body + "\n"
        "<script>hljs.highlightAll();</script>\n"
        "<script>renderMathInElement(document.body, {"
        "  delimiters: ["
        "    {left: '$$', right: '$$', display: true},"
        "    {left: '$', right: '$', display: false},"
        "    {left: '\\\\(', right: '\\\\)', display: false},"
        "    {left: '\\\\[', right: '\\\\]', display: true}"
        "  ]"
        "});</script>\n"
        "</body>\n</html>"
    )


def html_to_pdf(html_path, pdf_path, node_bin, puppeteer_dir, chrome_path):
    js_script = f"""
const puppeteer = require('{puppeteer_dir}');
(async () => {{
    const browser = await puppeteer.launch({{
        executablePath: '{chrome_path}',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--allow-file-access-from-files']
    }});
    const page = await browser.newPage();
    await page.goto('file://{html_path}', {{waitUntil: 'load', timeout: 30000}});
    // wait for mermaid to load, then trigger rendering explicitly
    await new Promise(r => setTimeout(r, 1000));
    await page.evaluate(() => {{
        mermaid.initialize({{startOnLoad:false, theme:'default',
            flowchart:{{nodeSpacing:20, rankSpacing:30}}}});
        mermaid.init(undefined, document.querySelectorAll('.mermaid'));
    }});
    await new Promise(r => setTimeout(r, 2000));
    const svgCount = await page.evaluate(() => document.querySelectorAll('.mermaid svg').length);
    console.log('Rendered ' + svgCount + ' mermaid diagram(s)');
    await page.pdf({{
        path: '{pdf_path}',
        format: 'A4',
        margin: {{top: '20mm', bottom: '20mm', left: '15mm', right: '15mm'}},
        printBackground: true
    }});
    await browser.close();
    console.log('PDF written to {pdf_path}');
}})();
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(js_script)
        js_path = f.name

    try:
        result = subprocess.run(
            [node_bin, js_path],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            print(f"Error: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        print(result.stdout.strip())
    finally:
        os.unlink(js_path)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} input.md [output.pdf]", file=sys.stderr)
        sys.exit(1)

    md_path = os.path.abspath(sys.argv[1])
    if len(sys.argv) > 2:
        pdf_path = os.path.abspath(sys.argv[2])
    else:
        pdf_path = md_path.rsplit(".", 1)[0] + ".pdf"

    print(f"Input:  {md_path}")
    print(f"Output: {pdf_path}")

    node_bin = find_node()
    puppeteer_dir, chrome_path = find_puppeteer()
    print(f"Node:   {node_bin}")
    print(f"Chrome: {chrome_path}")

    html_content = md_to_html(md_path)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, dir=os.path.dirname(pdf_path)
    ) as f:
        f.write(html_content)
        html_path = f.name

    try:
        html_to_pdf(html_path, pdf_path, node_bin, puppeteer_dir, chrome_path)
    finally:
        if os.path.exists(html_path):
            os.unlink(html_path)


if __name__ == "__main__":
    main()
