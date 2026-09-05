import re

def format_for_vk(text: str) -> str:
    """
    Cleans up and formats Markdown/HTML text for VK messages.
    VK messages do not support raw Markdown or HTML tags, so this converter
    transforms them into clean, polished mobile-friendly native VK text.
    """
    if not text:
        return ""

    # 1. Transform HTML tags
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<code>(.*?)</code>", r"«\1»", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<pre>(.*?)</pre>", lambda m: f"\n\n{m.group(1).strip()}\n\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?(?:b|strong)>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:i|em)>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)  # Strip any remaining unhandled HTML tags

    # 2. Transform markdown links [text](url) -> 'text (url)'
    text = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", text)

    # 3. Transform headers (# Header) -> '📌 Header'
    text = re.sub(r"^#{1,3}\s+(.+)$", r"📌 \1", text, flags=re.MULTILINE)

    # 4. Transform multi-line code blocks ```lang ... ``` into clean blocks separated by empty lines
    def format_code_block(match):
        code = match.group(1).strip()
        return f"\n\n{code}\n\n"
    text = re.sub(r"```(?:\w+)?\n?(.*?)```", format_code_block, text, flags=re.DOTALL)


    # 5. Transform inline backticks `code` -> «code»
    text = re.sub(r"`([^`]+)`", r"«\1»", text)

    # 6. Remove bold asterisks **text** -> text (since VK does not parse **)
    text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^\*]+)\*", r"\1", text)

    # 7. Normalize bullet lists (- item / * item -> • item)
    text = re.sub(r"^\s*[\-\*]\s+", r"• ", text, flags=re.MULTILINE)

    # 8. Strip excessive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

