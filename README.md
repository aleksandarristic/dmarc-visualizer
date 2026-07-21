# dmarc-visualizer

Analyse and visualize DMARC results using open-source tools.

* [parsedmarc](https://github.com/domainaware/parsedmarc) for parsing DMARC reports,
* [Elasticsearch](https://www.elastic.co/) to store aggregated data.
* [Grafana](https://grafana.com/) to visualize the aggregated reports.


## Screenshot

![Screenshot of Grafana dashboard](/big_screenshot.png?raw=true)


## Quickstart

```
git clone https://github.com/aleksandarristic/dmarc-visualiser
cd dmarc-visualiser
./start.sh
```


### Note on GeoIP information:
In order to have the geoip data populated and visible on the map in the dashboard, you will need to visit https://dev.maxmind.com/geoip/geolite2-free-geolocation-data?lang=en and get your own `GeoLite2-Country.mmdb` file, then put it in the `parsedmarc` directory before running docker-compose.


## Usage

### Setup (once)

`fetch_attachments.py` pulls DMARC report attachments from an IMAP mailbox
(e.g. Gmail) into `files/`. Copy the example config and fill it in:

```
cp fetch_attachments_example_config.json fetch_attachments_config.json
```

```json
{
    "auth": {
        "server": "imap.gmail.com",
        "username": "you@example.com",
        "password": "app-password"
    },
    "filter": {
        "label": "DMARC",
        "to": "dmarc-reports@example.com"
    },
    "local": { "directory": "files", "overwrite": true },
    "report": {
        "directory": "reports",
        "es_url": "http://localhost:9200"
    }
}
```

Notes:
* The config is gitignored — your credentials never get committed.
* For Gmail, enable 2FA and use an [App Password](https://myaccount.google.com/apppasswords), not your normal password.
* `label` is the IMAP mailbox/label name and is **case-sensitive** (Gmail labels appear verbatim, e.g. `DMARC`).
* The `report` section configures the weekly report (step 3 below) and is
  optional — these values are the defaults.

On the first run, backfill everything already in the mailbox:

```
python3 fetch_attachments.py --seen     # all messages, including already-read
```

### Weekly flow

#### 1. Fetch new reports

```
python3 fetch_attachments.py            # unread messages only
python3 fetch_attachments.py --since 01-Jan-2026   # or date-bounded
```

Fetching a message marks it read, so the next default run only picks up new reports.

#### 2. Parse and visualize

```
docker compose up -d                    # parsedmarc parses files/ into Elasticsearch, then exits
```

Elasticsearch and Grafana keep running; parsedmarc is a one-shot batch job.
View the dashboards at **http://localhost:3000** (anonymous access enabled).

Check that parsing succeeded:

```
docker compose ps                       # parsedmarc should show "Exited (0)"
tail -n 20 output_files/parsedmarc.log
curl -s 'localhost:9200/_cat/indices/dmarc*?v&h=index,docs.count'
```

(Elasticsearch is published host-only on `127.0.0.1:9200`.)

#### 3. Generate the weekly report

`weekly_report.py` queries Elasticsearch (it does not re-read `files/`) and
summarizes the last 7 days vs. the 7 before: volume, DMARC pass rate,
SPF/DKIM alignment failures, top failing sources, and any sending sources
never seen before. Each report is saved to `reports/` (gitignored) and
printed to stdout.

```
python3 weekly_report.py                # writes reports/dmarc_<start>_to_<end>.txt
python3 weekly_report.py --days 30 --end 2026-07-01   # custom window
```

#### 4. Housekeeping (optional)

```
python3 archive_files.py                # move already-parsed files older than 8 days to .old/
```

When done, stop everything with `docker compose down` — parsed data persists
in the `elastic_data/` volume.

## Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                        # unit tests for the fetcher
```

## Thanks:

* https://github.com/debricked/dmarc-visualizer - original code

See the full blog post with instructions at https://debricked.com/blog/2020/05/14/analyse-and-visualize-dmarc-results-using-open-source-tools/.