import re

def format_for_vk(text: str) -> str:
    """
    Cleans up and formats Markdown text for VK messages.
    VK does not support raw Markdown tags (**bold**, `code`), so this converter
    transforms them into clean, polished mobile-friendly text.
    """
    if not text:
        return ""

    # 1. Transform markdown links [text](url) -> 'text (url)'
    text = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", text)

    # 2. Transform headers (# Header) -> '📌 Header'
    text = re.sub(r"^#{1,3}\s+(.+)$", r"📌 \1", text, flags=re.MULTILINE)

    # 3. Transform multi-line code blocks ```lang ... ``` into clean quoted blocks
    def format_code_block(match):
        code = match.group(1).strip()
        return f"\n──────────────\n{code}\n──────────────\n"
    text = re.sub(r"```(?:\w+)?\n?(.*?)```", format_code_block, text, flags=re.DOTALL)

    # 4. Transform inline backticks `code` -> «code»
    text = re.sub(r"`([^`]+)`", r"«\1»", text)

    # 5. Remove bold asterisks **text** -> text (since VK does not parse **)
    text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^\*]+)\*", r"\1", text)

    # 6. Normalize bullet lists (- item / * item -> • item)
    text = re.sub(r"^\s*[\-\*]\s+", r"• ", text, flags=re.MULTILINE)

    # 7. Strip excessive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
