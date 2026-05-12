#!/usr/bin/env bash
# md-to-adf.sh — Markdown to Jira ADF (Atlassian Document Format) converter.
#
# Source this file to get the render_markdown_to_adf function.
#
# Usage:
#   source scripts/md-to-adf.sh
#   render_markdown_to_adf path/to/file.md   # from file
#   echo '# Hello' | render_markdown_to_adf  # from stdin

render_markdown_to_adf() {
  local input_file="${1:-}"

  python3 - "$input_file" <<'PYEOF'
import sys, re, json

# ---------------------------------------------------------------------------
# Inline parser
# ---------------------------------------------------------------------------

INLINE_RE = re.compile(
    r'`(?P<code>[^`]+)`'
    r'|\*\*(?P<bold>.+?)\*\*'
    r'|__(?P<bold2>.+?)__'
    r'|\*(?P<em>[^*\n]+)\*'
    r'|_(?P<em2>[^_\n]+)_'
    r'|~~(?P<strike>.+?)~~'
    r'|\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]+)\)'
)

def parse_inline(text):
    """Convert markdown inline syntax to a list of ADF inline nodes."""
    if not text:
        return []
    nodes = []
    last_end = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > last_end:
            nodes.append({"type": "text", "text": text[last_end:m.start()]})
        if m.group('code'):
            nodes.append({"type": "text", "text": m.group('code'),
                          "marks": [{"type": "code"}]})
        elif m.group('bold') or m.group('bold2'):
            nodes.append({"type": "text", "text": m.group('bold') or m.group('bold2'),
                          "marks": [{"type": "strong"}]})
        elif m.group('em') or m.group('em2'):
            nodes.append({"type": "text", "text": m.group('em') or m.group('em2'),
                          "marks": [{"type": "em"}]})
        elif m.group('strike'):
            nodes.append({"type": "text", "text": m.group('strike'),
                          "marks": [{"type": "strike"}]})
        elif m.group('link_text'):
            nodes.append({"type": "text", "text": m.group('link_text'),
                          "marks": [{"type": "link",
                                     "attrs": {"href": m.group('link_url')}}]})
        last_end = m.end()
    if last_end < len(text):
        nodes.append({"type": "text", "text": text[last_end:]})
    return nodes or [{"type": "text", "text": text}]

# ---------------------------------------------------------------------------
# Block parser
# ---------------------------------------------------------------------------

HEADING_RE    = re.compile(r'^(#{1,6})\s+(.+)$')
BULLET_RE     = re.compile(r'^([-*+])\s+(.*)$')
ORDERED_RE    = re.compile(r'^(\d+)\.\s+(.*)$')
RULE_RE       = re.compile(r'^[-*_]{3,}\s*$')
FENCE_OPEN_RE = re.compile(r'^```(\w*)$')
FENCE_CLOSE_RE= re.compile(r'^```\s*$')
BLOCKQUOTE_RE = re.compile(r'^>\s?(.*)')

def parse_blocks(lines):
    """Parse a list of text lines into a list of ADF block nodes."""
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        fm = FENCE_OPEN_RE.match(line)
        if fm:
            lang = fm.group(1)
            i += 1
            code_lines = []
            while i < len(lines) and not FENCE_CLOSE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            node = {"type": "codeBlock",
                    "attrs": {"language": lang},
                    "content": [{"type": "text", "text": "\n".join(code_lines)}]}
            blocks.append(node)
            continue

        # Heading
        hm = HEADING_RE.match(line)
        if hm:
            blocks.append({"type": "heading",
                           "attrs": {"level": len(hm.group(1))},
                           "content": parse_inline(hm.group(2))})
            i += 1
            continue

        # Horizontal rule
        if RULE_RE.match(line):
            blocks.append({"type": "rule"})
            i += 1
            continue

        # Bullet list — consume consecutive bullet items (including indented continuations)
        if BULLET_RE.match(line):
            items = []
            while i < len(lines):
                bm = BULLET_RE.match(lines[i])
                if bm:
                    items.append({"type": "listItem",
                                  "content": [{"type": "paragraph",
                                               "content": parse_inline(bm.group(2))}]})
                    i += 1
                else:
                    break
            blocks.append({"type": "bulletList", "content": items})
            continue

        # Ordered list
        if ORDERED_RE.match(line):
            items = []
            while i < len(lines):
                om = ORDERED_RE.match(lines[i])
                if om:
                    items.append({"type": "listItem",
                                  "content": [{"type": "paragraph",
                                               "content": parse_inline(om.group(2))}]})
                    i += 1
                else:
                    break
            blocks.append({"type": "orderedList", "content": items})
            continue

        # Blockquote
        qm = BLOCKQUOTE_RE.match(line)
        if qm:
            quote_lines = []
            while i < len(lines):
                qm2 = BLOCKQUOTE_RE.match(lines[i])
                if qm2:
                    quote_lines.append(qm2.group(1))
                    i += 1
                else:
                    break
            inner = parse_blocks(quote_lines)
            blocks.append({"type": "blockquote", "content": inner})
            continue

        # Empty line — skip
        if line.strip() == "":
            i += 1
            continue

        # Paragraph — collect until blank line or block-level element
        para_lines = []
        while i < len(lines):
            l = lines[i]
            if (l.strip() == "" or HEADING_RE.match(l) or FENCE_OPEN_RE.match(l)
                    or BULLET_RE.match(l) or ORDERED_RE.match(l)
                    or BLOCKQUOTE_RE.match(l) or RULE_RE.match(l)):
                break
            para_lines.append(l)
            i += 1
        if para_lines:
            content = parse_inline(" ".join(para_lines))
            if content:
                blocks.append({"type": "paragraph", "content": content})

    return blocks

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else ""
    if path:
        with open(path, encoding="utf-8") as f:
            md = f.read()
    else:
        md = sys.stdin.read()

    if not md.strip():
        print("null")
        return

    lines = md.splitlines()
    blocks = parse_blocks(lines)
    adf = {"type": "doc", "version": 1, "content": blocks}
    print(json.dumps(adf, ensure_ascii=False))

main()
PYEOF
}
