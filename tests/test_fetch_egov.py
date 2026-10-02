import io
import urllib.error

import pytest

from jlawcite.pipeline import fetch_egov


def _http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO())


def test_download_retries_then_succeeds(monkeypatch, tmp_path):
    calls = []

    def fake(url, dest):
        calls.append(url)
        if len(calls) < 3:
            raise _http_error(403)
        dest.write_bytes(b"ok")

    monkeypatch.setattr(fetch_egov, "_download_once", fake)
    monkeypatch.setattr(fetch_egov.time, "sleep", lambda s: None)
    dest = tmp_path / "a.zip"
    fetch_egov.download("u", dest, delays=(1, 1, 1))
    assert len(calls) == 3 and dest.read_bytes() == b"ok"


def test_download_gives_up_after_retries(monkeypatch, tmp_path):
    calls = []

    def fake(url, dest):
        calls.append(url)
        raise _http_error(503)

    monkeypatch.setattr(fetch_egov, "_download_once", fake)
    monkeypatch.setattr(fetch_egov.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        fetch_egov.download("u", tmp_path / "a.zip", delays=(1, 1))
    assert len(calls) == 3


def test_download_does_not_retry_404(monkeypatch, tmp_path):
    calls = []

    def fake(url, dest):
        calls.append(url)
        raise _http_error(404)

    monkeypatch.setattr(fetch_egov, "_download_once", fake)
    monkeypatch.setattr(fetch_egov.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        fetch_egov.download("u", tmp_path / "a.zip", delays=(1, 1))
    assert len(calls) == 1
