#!/usr/bin/env python3
"""Tests for fetch_attachments.py.

Run with pytest (installed via requirements-dev.txt):

    python -m pytest -v
"""

import os
from email.message import EmailMessage

import pytest

import fetch_attachments as fa


# --- Fakes -----------------------------------------------------------------

class FakePart:
    """Minimal stand-in for an email MIME part used by extract_attachments."""

    def __init__(self, maintype='application', disposition='attachment',
                 filename='report.zip', payload=b'PK\x03\x04data'):
        self._maintype = maintype
        self._disposition = disposition
        self._filename = filename
        self._payload = payload

    def get_content_maintype(self):
        return self._maintype

    def get(self, key):
        if key == 'Content-Disposition':
            return self._disposition
        return None

    def get_filename(self):
        return self._filename

    def get_payload(self, decode=False):
        return self._payload


class FakeMessage:
    def __init__(self, parts):
        self._parts = parts

    def walk(self):
        return list(self._parts)


class FakeClient:
    """Stand-in for imaplib client: returns a canned FETCH response."""

    def __init__(self, resp_code, data):
        self._resp_code = resp_code
        self._data = data

    def fetch(self, email_id, spec):
        return self._resp_code, self._data


def rfc822_with_attachment(subject='Report domain: example.com',
                           filename='google.com!example.com!1!2.zip',
                           payload=b'PK\x03\x04zipbytes'):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = 'noreply@google.com'
    msg['To'] = 'dmarc-reports@example.com'
    msg.set_content('DMARC aggregate report attached.')
    msg.add_attachment(payload, maintype='application', subtype='zip',
                       filename=filename)
    return msg.as_bytes()


# --- build_query -----------------------------------------------------------

def test_default_is_unseen_only():
    assert fa.build_query() == ('UNSEEN',)


def test_unseen_with_to():
    assert fa.build_query(to='dmarc-reports@example.com') == (
        'UNSEEN', 'TO', 'dmarc-reports@example.com',
    )


def test_seen_drops_unseen():
    assert fa.build_query(seen=True) == ()
    assert fa.build_query(seen=True, to='x@y.z') == ('TO', 'x@y.z')


def test_since_and_before():
    assert fa.build_query(seen=True, since='01-Jan-2020', before='01-Feb-2020') == (
        'SINCE', '01-Jan-2020', 'BEFORE', '01-Feb-2020',
    )


# --- safe_filename ---------------------------------------------------------

def test_safe_filename_strips_relative_traversal():
    assert fa.safe_filename('../../etc/passwd', '5', 1) == 'passwd'


def test_safe_filename_strips_absolute_path():
    assert fa.safe_filename('/abs/dir/report.zip', '5', 1) == 'report.zip'


def test_safe_filename_generates_when_missing():
    assert fa.safe_filename(None, '5', 3) == 'id_5_part-003.bin'
    assert fa.safe_filename('', '7', 2) == 'id_7_part-002.bin'


def test_safe_filename_plain_name_untouched():
    assert fa.safe_filename('report.zip', '1', 1) == 'report.zip'


# --- decode_subject --------------------------------------------------------

def test_decode_subject_missing():
    assert fa.decode_subject(EmailMessage()) == '(no subject)'


def test_decode_subject_plain():
    m = EmailMessage()
    m['Subject'] = 'Report domain: example.com'
    assert fa.decode_subject(m) == 'Report domain: example.com'


def test_decode_subject_encoded():
    m = EmailMessage()
    m['Subject'] = '=?utf-8?b?QsO8Y2hlcg==?='  # "Bücher"
    assert fa.decode_subject(m) == 'Bücher'


# --- extract_attachments ---------------------------------------------------

def test_multiple_attachments_all_yielded():
    msg = FakeMessage([
        FakePart(filename='a.zip', payload=b'aaa'),
        FakePart(filename='b.gz', payload=b'bbb'),
    ])
    results = list(fa.extract_attachments(msg, '1'))
    assert [f for f, _ in results] == ['a.zip', 'b.gz']
    assert [p for _, p in results] == [b'aaa', b'bbb']


def test_unnamed_attachments_get_unique_names():
    # Regression: ++part_counter used to be a no-op, collapsing all unnamed
    # attachments onto id_X_part-000.bin.
    msg = FakeMessage([
        FakePart(filename=None, payload=b'one'),
        FakePart(filename=None, payload=b'two'),
    ])
    names = [f for f, _ in fa.extract_attachments(msg, '9')]
    assert names == ['id_9_part-001.bin', 'id_9_part-002.bin']
    assert len(set(names)) == 2  # no collision


def test_text_xml_attachment_is_saved():
    # Regression: the old is_bin() gate skipped text attachments, dropping
    # uncompressed .xml DMARC reports.
    msg = FakeMessage([
        FakePart(maintype='text', filename='report.xml', payload=b'<feedback/>'),
    ])
    assert list(fa.extract_attachments(msg, '1')) == [('report.xml', b'<feedback/>')]


def test_multipart_container_skipped():
    msg = FakeMessage([FakePart(maintype='multipart', filename=None, payload=None)])
    assert list(fa.extract_attachments(msg, '1')) == []


def test_non_attachment_skipped():
    msg = FakeMessage([FakePart(disposition=None, payload=b'body')])
    assert list(fa.extract_attachments(msg, '1')) == []


def test_none_payload_skipped():
    msg = FakeMessage([FakePart(filename='x.zip', payload=None)])
    assert list(fa.extract_attachments(msg, '1')) == []


# --- save_attachment -------------------------------------------------------

def test_save_attachment_writes_file(tmp_path):
    path = tmp_path / 'r.zip'
    assert fa.save_attachment(b'data', str(path), overwrite=True) is True
    assert path.read_bytes() == b'data'


def test_save_attachment_overwrite_false_skips_existing(tmp_path):
    path = tmp_path / 'r.zip'
    path.write_bytes(b'original')
    assert fa.save_attachment(b'new', str(path), overwrite=False) is False
    assert path.read_bytes() == b'original'  # untouched


def test_save_attachment_overwrite_true_replaces(tmp_path):
    path = tmp_path / 'r.zip'
    path.write_bytes(b'original')
    assert fa.save_attachment(b'new', str(path), overwrite=True) is True
    assert path.read_bytes() == b'new'


# --- get_mail_by_id (end-to-end with a fake IMAP client) -------------------

def test_get_mail_saves_real_message_attachment(tmp_path):
    raw = rfc822_with_attachment(filename='google.com!example.com!1!2.zip',
                                 payload=b'PK\x03\x04zipbytes')
    client = FakeClient('OK', [(b'1 (RFC822 {123}', raw), b')'])
    cfg = {'download_dir': str(tmp_path), 'overwrite': True}
    saved = fa.get_mail_by_id('1', client, cfg)
    assert saved == 1
    out = tmp_path / 'google.com!example.com!1!2.zip'
    assert out.is_file()
    assert out.read_bytes() == b'PK\x03\x04zipbytes'


def test_get_mail_bad_fetch_shape_returns_zero(tmp_path):
    # Server returned a flags line, not the (header, body) tuple.
    client = FakeClient('OK', [b'1 (FLAGS (\\Seen))'])
    cfg = {'download_dir': str(tmp_path), 'overwrite': True}
    assert fa.get_mail_by_id('1', client, cfg) == 0
    assert list(tmp_path.iterdir()) == []  # nothing written, no crash


def test_get_mail_non_ok_response_returns_zero():
    client = FakeClient('NO', None)
    cfg = {'download_dir': '.', 'overwrite': True}
    assert fa.get_mail_by_id('1', client, cfg) == 0


def test_get_mail_missing_subject_does_not_crash(tmp_path):
    raw = rfc822_with_attachment(subject='', filename='r.zip', payload=b'z')
    client = FakeClient('OK', [(b'1 (RFC822 {1}', raw), b')'])
    cfg = {'download_dir': str(tmp_path), 'overwrite': True}
    assert fa.get_mail_by_id('1', client, cfg) == 1
