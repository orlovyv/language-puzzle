from __future__ import annotations

from pydantic import BaseModel


class AuthPayload(BaseModel):
    email: str
    password: str
    native_language: str | None = "ru"
    target_language: str | None = "en"
    captcha_token: str | None = None


class VerifyRegistrationPayload(BaseModel):
    email: str
    code: str


class DocumentPayload(BaseModel):
    title: str = "Untitled text"
    type: str = "text"
    language: str = "en"
    raw_text: str = ""


class StatusPayload(BaseModel):
    status: str
    confidence: float | None = None
    document_id: str | None = None
    refresh_analysis: bool | None = False


class TranslationPayload(BaseModel):
    translation_ru: str | None = None


class AnalyzePayload(BaseModel):
    refresh_important: bool | None = False


class ReviewPayload(BaseModel):
    user_word_id: str
    grade: int


class KnowledgeGoalPayload(BaseModel):
    goal: str


class KnowledgeAnalyzePayload(BaseModel):
    text: str = ""
    manual_topic: str | None = None
    bridge_topic: str | None = None
    starter_words: list[str] | None = None


class KnowledgeBridgePayload(BaseModel):
    context_id: str
    bridge_title: str
    starter_words: list[str] | None = None
    document_id: str | None = None


class LearnBlockPayload(BaseModel):
    title: str
    units: list[dict] = []


class LearnBlockUpdatePayload(BaseModel):
    frequency_filter: str | None = None


class LearnMergePayload(BaseModel):
    block_ids: list[str]


class CheckoutPayload(BaseModel):
    # Reserved for future plan selection; checkout currently uses the single
    # configured subscription price.
    plan: str | None = "premium"


class PasswordResetRequestPayload(BaseModel):
    email: str


class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str
