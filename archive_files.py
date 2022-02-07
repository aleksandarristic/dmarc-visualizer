#!/usr/bin/env python3

import argparse
import logging
import shutil
import os
from datetime import datetime, timedelta
import re


log = logging.getLogger(__name__)

FILES_DIR = 'files/'
ARCHIVE_DIR = '.old/'
DAYS_TO_KEEP = 8
regex = re.compile(r"(?P<from>\d{10})\!(?P<to>\d{10})", re.UNICODE)


def parse_args():
    parser = argparse.ArgumentParser(description=f'Archives older files to a specified directory.')
    parser.add_argument('--source', '-s', dest='source', help=f'Directory to read files from. Default: "{FILES_DIR}"')
    parser.add_argument('--destination', '-d', dest='destination', help=f'Directory to archive files to. Default: "{ARCHIVE_DIR}"')
    parser.add_argument('--overwrite', '-o', dest='overwrite', action='store_true', help=f'If this flag is set, overwrite files with matching names in the destination directory. Default: False')
    parser.add_argument('--keep', '-k', dest='keep', help=f'Number of days to keep. Default: {DAYS_TO_KEEP}')
    parser.add_argument('--run', dest='run', action='store_true', help='Skip interactive check - will always run the tool!')
    parser.add_argument('-v', dest='verbose', action='store_true', help='Verbose mode.')
    parser.set_defaults(source=FILES_DIR, destination=ARCHIVE_DIR, keep=DAYS_TO_KEEP, overwrite=False, run=False, verbose=False)
    args = parser.parse_args()
    configure_logging(args.verbose)
    return args


def configure_logging(verbose):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    file_handler = logging.FileHandler(filename='archive_files.log')
    handlers = [file_handler]

    if verbose:
        import sys
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S',
        handlers=handlers
    )


def should_move(file_name, days_to_keep):
    matches = re.search(regex, file_name)
    if not matches:
        log.warning(f'Match for file "{file_name}" not found.')
        return False

    today = datetime.date(datetime.utcnow())
    from_time = datetime.utcfromtimestamp(int(matches.groupdict()['from']))
    file_day = datetime.date(from_time)

    if today - file_day < timedelta(days=days_to_keep):
        return False

    return True


def move_file(src_path, dest_path, overwrite):
    if overwrite:
        dest_path = os.path.join(dest_path, os.path.split(src_path)[-1])
    shutil.move(src_path, dest_path)
    log.info(f'Moved file "{src_path}" to "{dest_path}" with overwrite={overwrite}.')


def main():
    args = parse_args()

    if not args.run:
        print(f'You are about to archive files from "{args.source}" older than {args.keep} days to "{args.destination}".')
        print(f'Files with matching names will', '%s' % 'be' if args.overwrite else 'not be', 'overwritten.')
        answer = input('Type yes to continue: ')
        if not answer.lower() in ['y', 'yes']:
            print('Exiting.')
            quit(0)
        print('Continuing.')

    moved = 0
    for root, dirs, files in os.walk(args.source):
        for file_name in files:
            file_path = os.path.join(args.source, file_name)
            if should_move(file_name, args.keep):
                try:
                    move_file(file_path, args.destination, args.overwrite)
                    moved += 1
                except Exception as e:
                    log.error(f'ERROR: {e}.')

    log.info(f'Finished moving {moved} files.')
    print(f'Moved {moved} files to from "{args.source}" to "{args.destination}".')


if __name__ == '__main__':
    main()
