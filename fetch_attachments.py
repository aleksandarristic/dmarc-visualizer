#!/usr/bin/env python3

import argparse
import email
import imaplib
import os
import json
import logging

log = logging.getLogger(__name__)

text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})


def is_bin(chars) -> bool:
    if len(chars) >= 1024:
        chars = chars[:1024]
    return bool(chars.translate(None, text_chars))


def parse_args():
    parser = argparse.ArgumentParser(description=f'Fetch attachments of emails under specific label')
    parser.add_argument('--id', dest='email_ids', nargs='*', default=None, help='Optional email IDs')
    parser.add_argument('--since', dest='since', default=None, help='Date to search from (eg: 01-Jan-2020)')
    parser.add_argument('--before', dest='before', default=None, help='Date to search until (eg: 01-Jan-2022)')
    parser.add_argument('--seen', dest='seen', default=False, action='store_true', help='Include read emails.')

    parser.add_argument('--debug', dest='debug', default=False, action='store_true', help='Debug mode.')
    args = parser.parse_args()
    return args


def load_config(config_file='fetch_attachments_config.json'):
    with open(config_file, 'r') as f:
        config = json.loads(f.read())

    cfg = {
        'server': config.get('auth', {}).get('server'),
        'username': config.get('auth', {}).get('username'),
        'password': config.get('auth', {}).get('password'),
        'label': config.get('filter', {}).get('label'),
        'to': config.get('filter', {}).get('to'),
        'download_dir': config.get('local', {}).get('directory', '.'),
        'overwrite': config.get('local', {}).get('overwrite', True)
    }

    if not (cfg['server'] and cfg['username'] and cfg['password'] and cfg['label'] and cfg['to']):
        raise ValueError('Configuration error')

    return cfg


def configure_logging(verbose, debug=False):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    file_handler = logging.FileHandler(filename='fetch_attachments.log')
    handlers = [file_handler]

    if verbose:
        import sys
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO if not debug else logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S',
        handlers=handlers
    )


def get_mail_by_id(email_id, client, cfg):
    log.info(f'Working on email id {email_id}')
    resp_code, data = client.fetch(email_id, "(RFC822)")
    email_body = data[0][1]  # hackity hack - unsafe
    message = email.message_from_bytes(email_body)

    log.info('Parsing email "' + message['Subject'] + '"')

    part_counter = 0
    for part in message.walk():
        # skip multipart containers
        if part.get_content_maintype() == 'multipart':
            continue

        # skip if not an attachment
        if part.get('Content-Disposition') is None:
            continue

        filename = part.get_filename()

        # safety for attachments without filename
        if not filename:
            filename = 'id_%s_part-%03d%s' % (email_id, ++part_counter, '.bin')

        attachment_path = os.path.join(cfg['download_dir'], filename)

        if not os.path.isfile(attachment_path) or cfg['overwrite']:
            log.info(f'Saving attachment to {attachment_path}...')
            payload = part.get_payload(decode=True)
            if is_bin(payload):
                with open(attachment_path, 'wb') as f:
                    f.write(payload)
                    log.info('Attachment saved.')
            else:
                log.info('Attachment is text, skipped')


def build_query(seen=False, since=None, before=None, to=None):
    q = []
    if since:
        q.append('SINCE')
        q.append(since)

    if before:
        q.append('BEFORE')
        q.append(before)

    if not seen:
        q.append('UNSEEN')

    if to:
        q.append('TO')
        q.append(to)

    return tuple(q)


def main():
    args = parse_args()
    configure_logging(verbose=True, debug=args.debug)

    try:
        cfg = load_config()
    except ValueError as e:
        cfg = None
        log.error(f'Error loading config: {e}')
        quit(-1)

    client = imaplib.IMAP4_SSL(cfg['server'])
    log.info('Logging in to server...')
    try:
        client.login(cfg['username'], cfg['password'])
    except Exception as e:
        log.error(f'ERROR LOGGING IN: {e}')
        quit(-1)
    log.debug('Login Success!')

    client.select(cfg['label'])

    if args.email_ids:  # extract specific emails by email_id, no need for search
        email_ids = args.email_ids
    else:  # build a query and run a search
        query = build_query(seen=args.seen, since=args.since, before=args.before, to=cfg['to'])
        log.debug(f'Generated query: {query}')
        resp_code, email_ids = client.search(None, *query)
        email_ids = [a.decode() for a in email_ids[0].split()]  # getting the mails id

    if not email_ids:
        log.info('No unseen emails detected.')
    else:
        log.info(f'Downloading emails with ids: {", ".join(map(str, email_ids))}')

        for email_id in email_ids:
            get_mail_by_id(email_id, client, cfg=cfg)
    log.info('All done!')


if __name__ == '__main__':
    main()
