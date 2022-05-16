#!/usr/bin/env python3

import email
import imaplib
import os
import json
import logging


log = logging.getLogger(__name__)


def load_config(config_file='fetch_attachments_config.json'):
    config = {}

    with open(config_file, 'r') as f:
        config = json.loads(f.read())

    SERVER = config.get('auth', {}).get('server')
    USERNAME = config.get('auth', {}).get('username')
    PASSWORD = config.get('auth', {}).get('password')
    
    LABEL = config.get('filter', {}).get('label')
    TO = config.get('filter', {}).get('to')
    
    DOWNLOAD_DIR = config.get('local', {}).get('directory', '.')
    OVERWRITE = config.get('local', {}).get('overwrite', True)

    if not SERVER or not USERNAME or not PASSWORD or not LABEL or not TO:
        raise ValueError('Configuration error')

    return SERVER, USERNAME, PASSWORD, LABEL, TO, DOWNLOAD_DIR, OVERWRITE


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


def main():
    configure_logging(verbose=True)
    try:
        SERVER, USERNAME, PASSWORD, LABEL, TO, DOWNLOAD_DIR, OVERWRITE = load_config()
    except ValueError as e:
        log.error(f'Error loading config: {e}')
        quit(-1)

    client = imaplib.IMAP4_SSL(SERVER)
    log.info('Logging in to server...')
    try:
        client.login(USERNAME, PASSWORD)
    except Exception as e:
        log.error(f'ERROR LOGGING IN: {e}')
        quit(-1)
    log.info('Success!')

    client.select(LABEL)

    resp_code, email_ids = client.search(None, 'UNSEEN', 'TO', TO)
    email_ids = email_ids[0].split() # getting the mails id

    if not email_ids:
        log.info('No unseen emails detected.')
    else:

        log.info(f'Detected new emails with ids: {", ".join(map(str, email_ids))}')

        for email_id in email_ids:
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

                attachment_path = os.path.join(DOWNLOAD_DIR, filename)

                if not os.path.isfile(attachment_path) or OVERWRITE:
                    log.info(f'Saving attachment to {attachment_path}...')
                    with open(attachment_path, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    log.info('Attachment saved.')
    log.info('All done!')


if __name__ == '__main__':
    main()
