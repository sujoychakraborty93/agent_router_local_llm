from app.config import CLASSIFICATION_TO_MODEL


def model_for_classification(classification: str) -> str:
    return CLASSIFICATION_TO_MODEL[classification]
