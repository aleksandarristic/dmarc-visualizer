#!/usr/bin/env python3

import argparse
import email
import imaplib
import os
import json
import logging

log = logging.getLogger(__name__)

# M.search(None, '(SINCE "01-Jan-2012")')
# M.search(None, '(BEFORE "01-Jan-2012")')
# M.search(None, '(SINCE "01-Jan-2012" BEFORE "02-Jan-2012")')


def parse_args():
    parser = argparse.ArgumentParser(description=f'Fetch attachments of emails under specific label')
    parser.add_argument('--id', dest='email_ids', nargs='*', help='Optional email IDs')
    parser.set_defaults(email_ids=None)
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


def configure_logging(verbose):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    file_handler = logging.FileHandler(filename='fetch_attachments.log')
    handlers = [file_handler]

    if verbose:
        import sys
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S',
        handlers=handlers
    )


def get_mail_by_id(email_id, client, cfg):
    log.info(f'Working on email id {email_id}')
    resp_code, data = client.fetch(email_id, "(RFC822)")
    email_body = data[0][1]  # hackity hack - unsafe
    message = email.message_from_bytes(email_body)

    log.info('Parsing email "' + message['Subject'] + '"')

    for part in message.walk():
        # skip multipart containers
        if part.get_content_maintype() == 'multipart':
            continue

        # skip if not an attachment
        if part.get('Content-Disposition') is None:
            continue

        filename = part.get_filename()

        # safety for attachments without filename
        counter = 1
        if not filename:
            filename = 'part-%03d%s' % (counter, 'bin')
            counter += 1

        attachment_path = os.path.join(cfg['download_dir'], filename)

        if not os.path.isfile(attachment_path) or cfg['overwrite']:
            log.info(f'Saving attachment to {attachment_path}...')
            with open(attachment_path, 'wb') as f:
                f.write(part.get_payload(decode=True))
            log.info('Attachment saved.')


def main():
    configure_logging(verbose=True)
    args = parse_args()
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
    log.info('Login Success!')

    client.select(cfg['label'])

    if args.email_ids:
        email_ids = args.email_ids
    else:
        resp_code, email_ids = client.search(None, 'UNSEEN', 'TO', cfg['to'])
        email_ids = email_ids[0].split()  # getting the mails id

    if not email_ids:
        log.info('No unseen emails detected.')
    else:
        log.info(f'Downloading emails with ids: {", ".join(map(str, email_ids))}')

        for email_id in email_ids:
            get_mail_by_id(email_id, client, cfg=cfg)
    log.info('All done!')


if __name__ == '__main__':
    main()
