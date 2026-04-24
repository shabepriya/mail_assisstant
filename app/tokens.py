import tiktoken

from app.preprocess import emails_to_context


def count_tokens(text: str, model: str) -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def trim_to_fit(
    emails: list[dict],
    token_budget: int,
    model: str,
    max_body_chars: int,
    trim_chunk: int = 3,
) -> list[dict]:
    """Remove oldest emails (end of list) in chunks until context fits budget."""
    trimmed = emails[:]
    while True:
        ctx = emails_to_context(trimmed, max_body_chars)
        if count_tokens(ctx, model) <= token_budget or not trimmed:
            break
        if len(trimmed) <= trim_chunk:
            trimmed = []
            break
        del trimmed[-trim_chunk:]
    return trimmed
