from app.config import MODEL_PRICING


def compute_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    prices = MODEL_PRICING[model_id]
    return (input_tokens / 1_000_000) * prices["input"] + (output_tokens / 1_000_000) * prices["output"]
