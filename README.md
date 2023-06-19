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


## Thanks:

* https://github.com/debricked/dmarc-visualizer - original code

See the full blog post with instructions at https://debricked.com/blog/2020/05/14/analyse-and-visualize-dmarc-results-using-open-source-tools/.