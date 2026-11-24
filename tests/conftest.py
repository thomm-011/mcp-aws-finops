"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import resources

import pytest

from mcp_aws_finops.server import create_server
from mcp_aws_finops.sources.focus_file import FocusFileSource


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
