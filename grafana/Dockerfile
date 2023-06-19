#FROM grafana/grafana:8.5.6
FROM grafana/grafana:8.5.4

ADD --chown=grafana:root Grafana-DMARC_Reports.json /var/lib/grafana/dashboards/
RUN chmod 644 /etc/grafana/provisioning

COPY grafana-provisioning/ /etc/grafana/provisioning/
