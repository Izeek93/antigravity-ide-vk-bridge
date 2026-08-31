import re

def format_for_vk(text: str) -> str:
    """
    Cleans up and formats Markdown text for VK messages.
    Preserves bold readability, code blocks, lists and emojis.
    """
    if not text:
        return ""
        
    # Replace markdown links [text](url) with 'text: url' or 'text (url)'
    text = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", text)
    
    # Clean double asterisks if needed or keep standard
    # Convert headers (# Header) to clean bold/emoji style
    text = re.sub(r"^#{1,3}\s+(.+)$", r"📌 \1", text, flags=re.MULTILINE)
    
    # Strip excessive empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    return text.strip()
