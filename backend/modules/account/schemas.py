"""Account API wire schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PublicDemoConfigResponse(BaseModel):
    enabled: bool = False
    project_id: str | None = None
    version: str | None = None
    rp_enabled: bool = False


class AuthConfigResponse(BaseModel):
    auth_mode: str
    email_enabled: bool
    wechat_enabled: bool
    terms_version: str
    privacy_version: str
    terms_url: str = "/legal/terms"
    privacy_url: str = "/legal/privacy"
    support_email: str
    demo: PublicDemoConfigResponse = Field(default_factory=PublicDemoConfigResponse)


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class EmailCodeResponse(BaseModel):
    accepted: bool = True
    challenge_id: str | None = None
    expires_in: int = 300
    resend_after: int = 60


class EmailVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^\d{6}$")
    challenge_id: str
    accept_terms: bool = False
    accept_privacy: bool = False


class AccountMeResponse(BaseModel):
    id: str
    status: str
    identity_type: str
    support_code: str
    deletion_requested_at: datetime | None = None
    purge_after: datetime | None = None


class AnonymousRpSessionResponse(BaseModel):
    identity_type: str = "anonymous_rp"
    expires_at: datetime


class AnonymousRpSessionRequest(BaseModel):
    accept_terms: bool = False
    accept_privacy: bool = False


class DeletionStateResponse(BaseModel):
    status: str
    deletion_requested_at: datetime | None = None
    purge_after: datetime | None = None
