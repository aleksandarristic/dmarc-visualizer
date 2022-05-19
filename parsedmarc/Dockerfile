FROM python:3.9-alpine3.14

RUN apk add --update --no-cache build-base libxml2-dev libxslt-dev libffi-dev
RUN apk add --update --no-cache --virtual .build_deps build-base \
    && pip3 install -U parsedmarc \
    && apk del .build_deps

COPY parsedmarc.ini /
RUN mkdir /usr/share/GeoIP
COPY GeoLite2-Country.mmdb /usr/share/GeoIP/GeoLite2-Country.mmdb
