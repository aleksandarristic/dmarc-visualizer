#!/usr/bin/env python3
"""Generate a weekly DMARC summary from the Elasticsearch data populated by
parsedmarc.

The report is always saved as a file under the report directory (default:
reports/, gitignored) and also printed to stdout. Reads
fetch_attachments_config.json only for an optional [report] section
(Elasticsearch URL, report directory) — no credentials are needed.
"""

import argparse
import datetime
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

INDEX_PATTERN = 'dmarc_aggregate*'
TOP_N = 10
MAX_SOURCES = 500


def parse_args():
    parser = argparse.ArgumentParser(description='Generate a weekly DMARC summary from Elasticsearch')
    parser.add_argument('--days', dest='days', type=int, default=7,
                        help='Length of the report window in days (default: 7)')
    parser.add_argument('--end', dest='end', default=None,
                        help='End of the report window as YYYY-MM-DD (default: today, UTC)')
    parser.add_argument('--config', dest='config', default='fetch_attachments_config.json',
                        help='Path to the config file')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true', help='Debug mode.')
    return parser.parse_args()


def load_config(config_file='fetch_attachments_config.json'):
    try:
        with open(config_file, 'r') as f:
            config = json.loads(f.read())
    except OSError:
        config = {}  # the config is optional here; fall back to defaults

    report = config.get('report', {})
    return {
        'es_url': report.get('es_url', 'http://localhost:9200'),
        'report_dir': report.get('directory', 'reports'),
    }


def configure_logging(verbose, debug=False):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    file_handler = logging.FileHandler(filename='weekly_report.log')
    handlers = [file_handler]

    if verbose:
        import sys
        # stderr, so that report output on stdout stays clean for piping
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO if not debug else logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S',
        handlers=handlers
    )


def window_bounds(end, days):
    """Return (prev_start, cur_start, cur_end) dates for the current window
    [cur_start, cur_end) and the previous window [prev_start, cur_start)."""
    cur_start = end - datetime.timedelta(days=days)
    prev_start = end - datetime.timedelta(days=2 * days)
    return prev_start, cur_start, end


def es_search(es_url, body):
    url = f'{es_url}/{INDEX_PATTERN}/_search'
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def build_stats_query(start, end):
    count = {'count': {'sum': {'field': 'message_count'}}}
    aligned = lambda field, value: {'term': {field: value}}  # noqa: E731
    return {
        'size': 0,
        'query': {'range': {'date_range': {'gte': start.isoformat(), 'lt': end.isoformat()}}},
        'aggs': {
            'total': {'sum': {'field': 'message_count'}},
            'passed': {'filter': {'term': {'passed_dmarc': True}}, 'aggs': count},
            'spf_fail': {'filter': {'term': {'spf_aligned': False}}, 'aggs': count},
            'dkim_fail': {'filter': {'term': {'dkim_aligned': False}}, 'aggs': count},
            'spf_rescued': {'filter': {'bool': {'filter': [
                aligned('spf_aligned', False), aligned('dkim_aligned', True)]}}, 'aggs': count},
            'dkim_rescued': {'filter': {'bool': {'filter': [
                aligned('dkim_aligned', False), aligned('spf_aligned', True)]}}, 'aggs': count},
            'dispositions': {'terms': {'field': 'disposition.keyword', 'size': TOP_N}, 'aggs': count},
            'domains': {'terms': {'field': 'header_from.keyword', 'size': TOP_N, 'order': {'count': 'desc'}},
                        'aggs': {**count, 'passed': {'filter': {'term': {'passed_dmarc': True}}, 'aggs': count}}},
            'countries': {'terms': {'field': 'source_country.keyword', 'size': TOP_N,
                                    'order': {'count': 'desc'}}, 'aggs': count},
            'reporters': {'terms': {'field': 'org_name.keyword', 'size': TOP_N,
                                    'order': {'count': 'desc'}}, 'aggs': count},
            'sources': {'terms': {'field': 'source_base_domain.keyword', 'size': MAX_SOURCES}, 'aggs': count},
            'failing': {
                'filter': {'term': {'passed_dmarc': False}},
                'aggs': {
                    **count,
                    'by_source': {
                        'terms': {'field': 'source_ip_address.keyword', 'size': TOP_N,
                                  'order': {'count': 'desc'}},
                        'aggs': {**count, 'rdns': {'terms': {'field': 'source_reverse_dns.keyword', 'size': 1}}},
                    },
                    'spf_results': {'terms': {'field': 'spf_results.result.keyword', 'size': TOP_N},
                                    'aggs': count},
                    'dkim_results': {'terms': {'field': 'dkim_results.result.keyword', 'size': TOP_N},
                                     'aggs': count},
                    'dkim_selectors': {'terms': {'field': 'dkim_results.selector.keyword', 'size': TOP_N}},
                },
            },
        },
    }


def _bucket_count(bucket):
    return int(bucket.get('count', {}).get('value') or 0)


def extract_stats(response):
    aggs = response.get('aggregations', {})

    def buckets(name, path=None):
        agg = aggs.get(name, {})
        for step in path or []:
            agg = agg.get(step, {})
        return agg.get('buckets', [])

    failing_sources = []
    for bucket in buckets('failing', ['by_source']):
        rdns_buckets = bucket.get('rdns', {}).get('buckets', [])
        failing_sources.append({
            'ip': bucket['key'],
            'rdns': rdns_buckets[0]['key'] if rdns_buckets else '',
            'count': _bucket_count(bucket),
        })

    return {
        'total': int(aggs.get('total', {}).get('value') or 0),
        'passed': _bucket_count(aggs.get('passed', {})),
        'spf_fail': _bucket_count(aggs.get('spf_fail', {})),
        'dkim_fail': _bucket_count(aggs.get('dkim_fail', {})),
        'spf_rescued': _bucket_count(aggs.get('spf_rescued', {})),
        'dkim_rescued': _bucket_count(aggs.get('dkim_rescued', {})),
        'dmarc_fail': _bucket_count(aggs.get('failing', {})),
        'dispositions': {b['key']: _bucket_count(b) for b in buckets('dispositions')},
        'domains': [b['key'] for b in buckets('domains')],
        'domain_stats': {b['key']: {'total': _bucket_count(b), 'passed': _bucket_count(b.get('passed', {}))}
                         for b in buckets('domains')},
        'countries': {b['key']: _bucket_count(b) for b in buckets('countries') if b['key']},
        'reporters': [(b['key'], _bucket_count(b)) for b in buckets('reporters')],
        'sources': {b['key']: _bucket_count(b) for b in buckets('sources') if b['key']},
        'failing_sources': failing_sources,
        'failing_spf_results': {b['key']: _bucket_count(b) for b in buckets('failing', ['spf_results'])},
        'failing_dkim_results': {b['key']: _bucket_count(b) for b in buckets('failing', ['dkim_results'])},
        'failing_dkim_selectors': [b['key'] for b in buckets('failing', ['dkim_selectors'])],
    }


def find_previously_seen(es_url, field, values, before):
    """Return the subset of values for `field` that also appears before the current window."""
    if not values:
        return set()
    body = {
        'size': 0,
        'query': {'bool': {'filter': [
            {'terms': {field: sorted(values)}},
            {'range': {'date_range': {'lt': before.isoformat()}}},
        ]}},
        'aggs': {'seen': {'terms': {'field': field, 'size': MAX_SOURCES}}},
    }
    response = es_search(es_url, body)
    return {b['key'] for b in response.get('aggregations', {}).get('seen', {}).get('buckets', [])}


def pass_rate(stats):
    if not stats['total']:
        return None
    return 100.0 * stats['passed'] / stats['total']


def _fmt_rate(rate):
    return 'n/a' if rate is None else f'{rate:.1f}%'


def _fmt_counts(counts):
    return ', '.join(f'{k}: {v:,}' for k, v in sorted(counts.items(), key=lambda i: -i[1]))


def render_text(cur, prev, new_sources, new_countries, cur_start, cur_end):
    lines = [
        f'DMARC weekly report: {", ".join(cur["domains"]) or "(no reports received)"}',
        f'Window: {cur_start} to {cur_end} (previous window in parentheses)',
        '',
        f'  Messages:         {cur["total"]:>7,}   (prev {prev["total"]:,})',
        f'  DMARC pass rate:  {_fmt_rate(pass_rate(cur)):>7}   (prev {_fmt_rate(pass_rate(prev))})',
        f'  SPF not aligned:  {cur["spf_fail"]:>7,}   (prev {prev["spf_fail"]:,})',
        f'  DKIM not aligned: {cur["dkim_fail"]:>7,}   (prev {prev["dkim_fail"]:,})',
        '',
    ]

    lines.append('Per domain:')
    for domain in cur['domains']:
        stats = cur['domain_stats'][domain]
        rate = _fmt_rate(pass_rate(stats))
        prev_stats = prev['domain_stats'].get(domain)
        prev_note = (f'(prev {prev_stats["total"]:,} msgs, {_fmt_rate(pass_rate(prev_stats))})'
                     if prev_stats else '(not seen in previous window)')
        lines.append(f'  - {domain:<28} {stats["total"]:>7,} msgs   {rate:>6} pass   {prev_note}')
    if not cur['domains']:
        lines.append('  (none)')
    lines.append('')

    dispositions = _fmt_counts(cur['dispositions']) or 'none'
    lines.append(f'Dispositions: {dispositions}')
    lines.append('')

    lines.append('Alignment failure detail:')
    lines.append(f'  SPF not aligned, DKIM saved it:  {cur["spf_rescued"]:>7,}')
    lines.append(f'  DKIM not aligned, SPF saved it:  {cur["dkim_rescued"]:>7,}')
    lines.append(f'  Both failed (DMARC fail):        {cur["dmarc_fail"]:>7,}')
    if cur['dmarc_fail']:
        if cur['failing_spf_results']:
            lines.append(f'  SPF results on failing mail:  {_fmt_counts(cur["failing_spf_results"])}')
        if cur['failing_dkim_results']:
            lines.append(f'  DKIM results on failing mail: {_fmt_counts(cur["failing_dkim_results"])}')
        if cur['failing_dkim_selectors']:
            lines.append(f'  DKIM selectors on failing mail: {", ".join(cur["failing_dkim_selectors"])}')
    lines.append('')

    if cur['countries']:
        marked = {f'{c}*' if c in new_countries else c: n for c, n in cur['countries'].items()}
        legend = '   (* first time seen)' if new_countries else ''
        lines.append(f'Source countries: {_fmt_counts(marked)}{legend}')
        lines.append('')

    lines.append('New sending sources (never seen before this window):')
    if new_sources:
        for domain in sorted(new_sources):
            lines.append(f'  - {domain} ({cur["sources"].get(domain, 0):,} messages)')
    else:
        lines.append('  (none)')
    lines.append('')

    lines.append('Top sources failing DMARC:')
    if cur['failing_sources']:
        for source in cur['failing_sources']:
            rdns = source['rdns'] or '(no reverse DNS)'
            lines.append(f'  - {source["ip"]:<40} {rdns:<40} {source["count"]:,}')
    else:
        lines.append('  (none)')
    lines.append('')

    reporters = ', '.join(f'{name}: {count:,}' for name, count in cur['reporters']) or '(none)'
    lines.append(f'Reports received from: {reporters}')
    return '\n'.join(lines)


def report_path(report_dir, cur_start, cur_end):
    return os.path.join(report_dir, f'dmarc_{cur_start}_to_{cur_end}.txt')


def save_report(text, report_dir, cur_start, cur_end):
    """Write the report into report_dir and return its path."""
    os.makedirs(report_dir, exist_ok=True)
    path = report_path(report_dir, cur_start, cur_end)
    with open(path, 'w') as f:
        f.write(text + '\n')
    log.info(f'Report saved to {path}')
    return path


def main():
    args = parse_args()
    configure_logging(verbose=True, debug=args.debug)

    cfg = load_config(args.config)

    if args.end:
        end = datetime.date.fromisoformat(args.end)
    else:
        end = datetime.datetime.now(datetime.timezone.utc).date()
    prev_start, cur_start, cur_end = window_bounds(end, args.days)

    try:
        cur = extract_stats(es_search(cfg['es_url'], build_stats_query(cur_start, cur_end)))
        prev = extract_stats(es_search(cfg['es_url'], build_stats_query(prev_start, cur_start)))
        seen_sources = find_previously_seen(
            cfg['es_url'], 'source_base_domain.keyword', set(cur['sources']), cur_start)
        seen_countries = find_previously_seen(
            cfg['es_url'], 'source_country.keyword', set(cur['countries']), cur_start)
    except urllib.error.URLError as e:
        log.error(f'Could not query Elasticsearch at {cfg["es_url"]}: {e}. '
                  'Is the stack running? Try: docker compose up -d')
        quit(-1)

    new_sources = set(cur['sources']) - seen_sources
    new_countries = set(cur['countries']) - seen_countries
    text = render_text(cur, prev, new_sources, new_countries, cur_start, cur_end)

    print(text)
    save_report(text, cfg['report_dir'], cur_start, cur_end)
    log.info('All done!')


if __name__ == '__main__':
    main()
