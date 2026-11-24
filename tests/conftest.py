"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import resources

import pytest

from mcp_aws_finops.server import create_server
from mcp_aws_finops.sources.focus_file import FocusFileSource


@pytest.fixture(autouse=True)
def _fake_aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test accidentally make a real AWS call.

    Fake, obviously-invalid credentials in the environment mean boto3 never
    falls back to real instance-profile/SSO credentials, and Stubber/moto
    intercept every client call before it reaches the network anyway.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def sample_data_path() -> str:
    return str(resources.files("mcp_aws_finops.data").joinpath("sample_focus.parquet"))


@pytest.fixture
def source(sample_data_path: str) -> Iterator[FocusFileSource]:
    src = FocusFileSource(sample_data_path)
    yield src
    src.close()


@pytest.fixture
def server(source: FocusFileSource):  # type: ignore[no-untyped-def]
    return create_server(source)
