from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from cassetter._core import MatchConfig, SecurityConfig
from cassetter._state import acquire_patches, current_cassette, release_patches
from cassetter.cassette import BeforeRecordRequest, BeforeRecordResponse, Cassette
from cassetter.intercept._registry import resolve_interceptors
from cassetter.recording import RecordMode

if TYPE_CHECKING:
    from cassetter._core import Matcher


@dataclass(frozen=True, kw_only=True, slots=True)
class Cassetter:
    """Reusable cassette configuration.

    Holds the options shared by a group of cassettes so they are declared once instead of on every
    `use_cassette()` call:

    ```python
    recorder = Cassetter(cassette_library_dir="tests/cassettes", record_mode="none")

    with recorder.use_cassette("openai.yaml") as cassette:
        ...
    ```

    Options left unset fall back to the same defaults as `use_cassette()`.
    """

    cassette_library_dir: str | os.PathLike[str] | None = None
    record_mode: RecordMode | str | None = None
    match_on: list[Matcher] | None = None
    ignore_json_paths: list[str] | None = None
    filter_headers: list[str] | None = None
    filter_query_parameters: list[str] | None = None
    body_scrub_patterns: list[str] | None = None
    filter_replacement: str | None = None
    intercept: list[str] | None = None
    max_age: str | None = None
    on_expiry: str | None = None
    ignore_localhost: bool = False
    ignore_hosts: list[str] | None = None
    before_record_request: BeforeRecordRequest | None = None
    before_record_response: BeforeRecordResponse | None = None

    def cassette(self, name: str | os.PathLike[str]) -> Cassette:
        """Build an unloaded cassette for `name`, resolved against `cassette_library_dir`.

        Args:
            name: Cassette file name, or a path. Absolute paths ignore `cassette_library_dir`.

        Returns:
            A cassette that has not read its file yet - call `load()` before using it.
        """
        record_mode = RecordMode.ONCE if self.record_mode is None else self.record_mode
        library_dir = self.cassette_library_dir
        path = os.fspath(name) if library_dir is None else os.path.join(library_dir, os.fspath(name))
        return Cassette(
            path,
            record_mode=RecordMode.from_str(record_mode) if isinstance(record_mode, str) else record_mode,
            match_config=MatchConfig(match_on=self.match_on, ignore_json_paths=self.ignore_json_paths),
            security_config=SecurityConfig(
                filter_headers=self.filter_headers,
                filter_query_parameters=self.filter_query_parameters,
                body_scrub_patterns=self.body_scrub_patterns,
                replacement=self.filter_replacement,
            ),
            max_age=self.max_age,
            on_expiry="warn" if self.on_expiry is None else self.on_expiry,
            ignore_localhost=self.ignore_localhost,
            ignore_hosts=self.ignore_hosts,
            before_record_request=self.before_record_request,
            before_record_response=self.before_record_response,
        )

    @contextlib.contextmanager
    def use_cassette(self, name: str | os.PathLike[str], **overrides: Any) -> Iterator[Cassette]:
        """Record/replay HTTP interactions into `name`.

        Args:
            name: Cassette file name, or a path. Absolute paths ignore `cassette_library_dir`.
            overrides: Any option of this configuration, replaced for this cassette only.
        """
        config = replace(self, **overrides) if overrides else self
        cassette = config.cassette(name)
        cassette.load()

        interceptor_classes = resolve_interceptors(config.intercept)

        acquire_patches(interceptor_classes)
        token = current_cassette.set(cassette)

        try:
            yield cassette
        finally:
            current_cassette.reset(token)
            release_patches(interceptor_classes)
            cassette.save()

    __call__ = use_cassette
