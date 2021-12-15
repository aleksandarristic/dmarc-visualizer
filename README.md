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
docker-compose -f ./docker-compose.yml --verbose up
```

And then visit http://localhost:3000


## Thanks:

* https://github.com/debricked/dmarc-visualizer - original code

See the full blog post with instructions at https://debricked.com/blog/2020/05/14/analyse-and-visualize-dmarc-results-using-open-source-tools/.