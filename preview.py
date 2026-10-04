"""Export test-rendered terminal previews; does not capture a desktop window."""
import asyncio
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from wcwidth import wcwidth

import cairosvg
from app import AtlasApp


def save_preview(app, path):
    svg = app.export_screenshot(title="DATABASE ATLAS / terminal test render")
    # Rich's default SVG references remote Fira Code. Keep previews offline and
    # use installed CJK glyphs; the live terminal still controls its own font.
    svg = re.sub(r"@font-face\s*\{.*?\}", "", svg, flags=re.S)
    svg = svg.replace("font-family: Fira Code, monospace;", 'font-family: "JetBrains Mono", monospace;')
    # Rich's SVG export sets textLength using len(), not terminal-cell width.
    # Place preview glyphs on the actual cell grid, with explicit local CJK
    # fallback. This is a rendering adapter only; the live TUI isn't changed.
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.fromstring(svg)
    for element in root.iter("{http://www.w3.org/2000/svg}text"):
        if "textLength" not in element.attrib:
            continue
        element.attrib.pop("textLength")
        offset = float(element.attrib.get("x", "0"))
        text = element.text or ""
        element.text = None
        for char in text:
            if char == "\n":
                continue
            width = max(0, wcwidth(char))
            span = ET.SubElement(element, "{http://www.w3.org/2000/svg}tspan")
            span.set("x", str(offset))
            span.set("font-family", "Noto Sans Mono CJK SC" if width == 2 else "JetBrains Mono")
            span.set("font-size", "22" if width == 2 else "20")
            span.text = char
            offset += width * 12.2
    svg = ET.tostring(root, encoding="unicode")
    path.with_suffix(".svg").write_text(svg, encoding="utf-8")
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(path.with_suffix(".png")))


async def main():
    directory = Path(__file__).parent / "previews"
    directory.mkdir(exist_ok=True)
    app = AtlasApp()
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.press("down", "down", "down")
        await pilot.pause()
        save_preview(app, directory / "01-relations")
        await pilot.press("4")
        await pilot.pause()
        save_preview(app, directory / "02-transactions")
        await pilot.press("9")
        app.panel_index = 0
        app.rebuild()
        await pilot.pause()
        save_preview(app, directory / "03-popularity")
        await pilot.press("0")
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        save_preview(app, directory / "04-compact")


if __name__ == "__main__":
    asyncio.run(main())
