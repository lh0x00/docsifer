"""Pydantic request/response models for the public API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OpenAIConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None

    def is_enabled(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def to_dict(self) -> dict[str, Any] | None:
        if not self.is_enabled():
            return None
        out: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            out["base_url"] = self.base_url
        if self.model:
            out["model"] = self.model
        return out


class HTTPConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cookies: dict[str, str] | None = None
    headers: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any] | None:
        out: dict[str, Any] = {}
        if self.cookies:
            out["cookies"] = self.cookies
        if self.headers:
            out["headers"] = self.headers
        return out or None


class ConvertSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cleanup: bool = Field(
        default=True,
        description="Strip <style>, <script> and hidden elements from HTML before conversion.",
    )


class ConvertResponse(BaseModel):
    filename: str
    markdown: str


class StatsResponse(BaseModel):
    access: dict[str, dict[str, int]] = Field(default_factory=dict)
    tokens: dict[str, dict[str, int]] = Field(default_factory=dict)
    healthy: bool = True


class HealthResponse(BaseModel):
    status: str
    version: str | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] | None = None
