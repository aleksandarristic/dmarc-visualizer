import datetime
import json

import weekly_report


def make_agg_response():
    """A realistic Elasticsearch aggregation response for one report window."""
    return {
        'aggregations': {
            'total': {'value': 1234.0},
            'passed': {'count': {'value': 1200.0}},
            'spf_fail': {'count': {'value': 40.0}},
            'dkim_fail': {'count': {'value': 22.0}},
            'spf_rescued': {'count': {'value': 6.0}},
            'dkim_rescued': {'count': {'value': 28.0}},
            'dispositions': {'buckets': [
                {'key': 'none', 'count': {'value': 1220.0}},
                {'key': 'quarantine', 'count': {'value': 14.0}},
            ]},
            'domains': {'buckets': [
                {'key': 'deyta.ai', 'count': {'value': 1200.0}, 'passed': {'count': {'value': 1180.0}}},
                {'key': 'staging.deyta.ai', 'count': {'value': 34.0}, 'passed': {'count': {'value': 20.0}}},
            ]},
            'countries': {'buckets': [
                {'key': 'US', 'count': {'value': 1200.0}},
                {'key': 'RS', 'count': {'value': 34.0}},
                {'key': '', 'count': {'value': 1.0}},
            ]},
            'reporters': {'buckets': [
                {'key': 'google.com', 'count': {'value': 900.0}},
                {'key': 'Enterprise Outlook', 'count': {'value': 334.0}},
            ]},
            'sources': {'buckets': [
                {'key': 'google.com', 'count': {'value': 1000.0}},
                {'key': 'sendgrid.net', 'count': {'value': 234.0}},
                {'key': '', 'count': {'value': 5.0}},
            ]},
            'failing': {
                'count': {'value': 34.0},
                'by_source': {'buckets': [
                    {'key': '203.0.113.9', 'count': {'value': 30.0},
                     'rdns': {'buckets': [{'key': 'mail.evil.example'}]}},
                    {'key': '198.51.100.7', 'count': {'value': 4.0}, 'rdns': {'buckets': []}},
                ]},
                'spf_results': {'buckets': [
                    {'key': 'softfail', 'count': {'value': 30.0}},
                    {'key': 'none', 'count': {'value': 4.0}},
                ]},
                'dkim_results': {'buckets': [{'key': 'fail', 'count': {'value': 34.0}}]},
                'dkim_selectors': {'buckets': [{'key': 'google'}, {'key': 's1'}]},
            },
        }
    }


def empty_stats():
    return weekly_report.extract_stats({})


class TestWindowBounds:
    def test_default_week(self):
        end = datetime.date(2026, 7, 21)
        prev_start, cur_start, cur_end = weekly_report.window_bounds(end, 7)
        assert cur_end == end
        assert cur_start == datetime.date(2026, 7, 14)
        assert prev_start == datetime.date(2026, 7, 7)

    def test_windows_are_contiguous_and_equal_length(self):
        prev_start, cur_start, cur_end = weekly_report.window_bounds(datetime.date(2026, 3, 1), 30)
        assert (cur_end - cur_start) == (cur_start - prev_start)


class TestExtractStats:
    def test_counts(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert stats['total'] == 1234
        assert stats['passed'] == 1200
        assert stats['spf_fail'] == 40
        assert stats['dkim_fail'] == 22
        assert stats['spf_rescued'] == 6
        assert stats['dkim_rescued'] == 28
        assert stats['dmarc_fail'] == 34
        assert stats['dispositions'] == {'none': 1220, 'quarantine': 14}
        assert stats['reporters'][0] == ('google.com', 900)

    def test_domain_stats(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert stats['domains'] == ['deyta.ai', 'staging.deyta.ai']
        assert stats['domain_stats']['staging.deyta.ai'] == {'total': 34, 'passed': 20}

    def test_countries_empty_key_dropped(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert stats['countries'] == {'US': 1200, 'RS': 34}

    def test_failing_detail(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert stats['failing_spf_results'] == {'softfail': 30, 'none': 4}
        assert stats['failing_dkim_results'] == {'fail': 34}
        assert stats['failing_dkim_selectors'] == ['google', 's1']

    def test_empty_source_domain_dropped(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert '' not in stats['sources']
        assert stats['sources'] == {'google.com': 1000, 'sendgrid.net': 234}

    def test_failing_sources_with_and_without_rdns(self):
        stats = weekly_report.extract_stats(make_agg_response())
        assert stats['failing_sources'][0] == {'ip': '203.0.113.9', 'rdns': 'mail.evil.example', 'count': 30}
        assert stats['failing_sources'][1]['rdns'] == ''

    def test_empty_response(self):
        stats = empty_stats()
        assert stats['total'] == 0
        assert stats['failing_sources'] == []
        assert stats['sources'] == {}
        assert stats['domain_stats'] == {}
        assert stats['countries'] == {}


class TestPassRate:
    def test_normal(self):
        assert weekly_report.pass_rate({'total': 200, 'passed': 150}) == 75.0

    def test_zero_total_is_none_not_crash(self):
        assert weekly_report.pass_rate({'total': 0, 'passed': 0}) is None
        assert weekly_report._fmt_rate(None) == 'n/a'


class TestRenderText:
    def render(self, cur=None, prev=None, new_sources=frozenset(), new_countries=frozenset()):
        return weekly_report.render_text(
            cur if cur is not None else empty_stats(),
            prev if prev is not None else empty_stats(),
            set(new_sources), set(new_countries),
            datetime.date(2026, 7, 14), datetime.date(2026, 7, 21))

    def test_contains_key_numbers(self):
        cur = weekly_report.extract_stats(make_agg_response())
        text = self.render(cur, new_sources={'sendgrid.net'})
        assert 'deyta.ai' in text
        assert '1,234' in text
        assert '97.2%' in text          # 1200/1234
        assert 'prev n/a' in text
        assert 'sendgrid.net (234 messages)' in text
        assert '203.0.113.9' in text
        assert 'mail.evil.example' in text
        assert '(no reverse DNS)' in text

    def test_per_domain_section(self):
        cur = weekly_report.extract_stats(make_agg_response())
        prev = weekly_report.extract_stats(make_agg_response())
        text = self.render(cur, prev)
        assert '58.8% pass' in text     # staging 20/34
        assert '(prev 34 msgs, 58.8%)' in text
        text_no_prev = self.render(cur)
        assert '(not seen in previous window)' in text_no_prev

    def test_failure_detail_section(self):
        cur = weekly_report.extract_stats(make_agg_response())
        text = self.render(cur)
        assert 'SPF not aligned, DKIM saved it' in text
        assert 'Both failed (DMARC fail):             34' in text
        assert 'softfail: 30' in text
        assert 'DKIM selectors on failing mail: google, s1' in text

    def test_failure_detail_omits_raw_results_when_all_pass(self):
        text = self.render()
        assert 'SPF results on failing mail' not in text

    def test_countries_with_new_marker(self):
        cur = weekly_report.extract_stats(make_agg_response())
        text = self.render(cur, new_countries={'RS'})
        assert 'US: 1,200' in text
        assert 'RS*: 34' in text
        assert '(* first time seen)' in text
        text_no_new = self.render(cur)
        assert '*' not in text_no_new.split('Source countries:')[1].split('\n')[0]

    def test_empty_week(self):
        text = self.render()
        assert '(no reports received)' in text
        assert 'n/a' in text
        assert 'Source countries' not in text
        # per-domain, new sources, failing sources and reporters all render as "(none)"
        assert text.count('(none)') == 4


class TestSaveReport:
    def test_creates_directory_and_file(self, tmp_path):
        report_dir = tmp_path / 'reports'
        path = weekly_report.save_report('report body', str(report_dir),
                                         datetime.date(2026, 7, 14), datetime.date(2026, 7, 21))
        assert path == str(report_dir / 'dmarc_2026-07-14_to_2026-07-21.txt')
        assert (report_dir / 'dmarc_2026-07-14_to_2026-07-21.txt').read_text() == 'report body\n'


class TestQueries:
    def test_stats_query_window(self):
        query = weekly_report.build_stats_query(datetime.date(2026, 7, 14), datetime.date(2026, 7, 21))
        assert query['query']['range']['date_range'] == {'gte': '2026-07-14', 'lt': '2026-07-21'}
        assert query['size'] == 0
        assert json.dumps(query)  # serializable

    def test_previously_seen_short_circuits_on_empty(self):
        # must not hit Elasticsearch at all when there are no values
        assert weekly_report.find_previously_seen(
            'http://nope:1', 'source_base_domain.keyword', set(), datetime.date(2026, 1, 1)) == set()

    def test_previously_seen_queries_before_window(self, monkeypatch):
        captured = {}

        def fake_search(es_url, body):
            captured['body'] = body
            return {'aggregations': {'seen': {'buckets': [{'key': 'google.com'}]}}}

        monkeypatch.setattr(weekly_report, 'es_search', fake_search)
        seen = weekly_report.find_previously_seen(
            'http://es:9200', 'source_base_domain.keyword', {'google.com', 'sendgrid.net'},
            datetime.date(2026, 7, 14))
        assert seen == {'google.com'}
        filters = captured['body']['query']['bool']['filter']
        assert {'range': {'date_range': {'lt': '2026-07-14'}}} in filters
        assert {'terms': {'source_base_domain.keyword': ['google.com', 'sendgrid.net']}} in filters


class TestLoadConfig:
    def test_report_section_overrides(self, tmp_path):
        config_file = tmp_path / 'config.json'
        config_file.write_text(json.dumps({
            'auth': {'username': 'me@example.com', 'password': 'secret'},
            'report': {'directory': 'weekly', 'es_url': 'http://other:9200'},
        }))
        cfg = weekly_report.load_config(str(config_file))
        assert cfg == {'es_url': 'http://other:9200', 'report_dir': 'weekly'}

    def test_missing_file_falls_back_to_defaults(self):
        cfg = weekly_report.load_config('does-not-exist.json')
        assert cfg == {'es_url': 'http://localhost:9200', 'report_dir': 'reports'}
