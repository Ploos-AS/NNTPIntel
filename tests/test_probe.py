from io import BytesIO

import pytest

from nntpintel.probe import NNTPProtocolError, _parse_status, _read_multiline, _readline


def test_parse_status():
    assert _parse_status("200 posting allowed") == (200, "posting allowed")
    assert _parse_status("201") == (201, "")


def test_parse_status_rejects_invalid_line():
    with pytest.raises(NNTPProtocolError):
        _parse_status("hello")


def test_readline_decodes_and_strips_crlf():
    assert _readline(BytesIO(b"200 hello\r\n")) == "200 hello"


def test_multiline_unstuffs_dot_lines():
    stream = BytesIO(b"VERSION 2\r\n..leading-dot\r\n.\r\n")
    assert _read_multiline(stream) == ["VERSION 2", ".leading-dot"]
