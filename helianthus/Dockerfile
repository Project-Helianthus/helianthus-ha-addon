# syntax=docker/dockerfile:1.6

ARG BUILD_FROM=ghcr.io/home-assistant/base:3.20
ARG VRCEXPLORER_VERSION=main

FROM golang:1.22-alpine AS builder
ARG TARGETARCH
ARG TARGETVARIANT
ARG EBUSGATEWAY_VERSION=main
ARG EBUSADAPTERPROXY_VERSION=main

RUN apk add --no-cache git ca-certificates

ENV CGO_ENABLED=0
ENV GOPRIVATE=github.com/d3vi1/*

RUN if [ "${TARGETARCH}" = "arm" ] && [ -n "${TARGETVARIANT}" ]; then export GOARM="${TARGETVARIANT#v}"; fi \
 && GOBIN=/out go install github.com/d3vi1/helianthus-ebusgateway/cmd/gateway@${EBUSGATEWAY_VERSION} \
 && GOBIN=/out go install github.com/d3vi1/helianthus-ebus-adapter-proxy/cmd/helianthus-ebus-adapter-proxy@${EBUSADAPTERPROXY_VERSION}

FROM python:3.12-alpine AS vrc-explorer
ARG VRCEXPLORER_VERSION=main

RUN apk add --no-cache git ca-certificates

RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir --target /out/python \
    "git+https://github.com/d3vi1/helianthus-vrc-explorer@${VRCEXPLORER_VERSION}"

FROM ${BUILD_FROM}
ARG VRCEXPLORER_VERSION=main

RUN apk add --no-cache python3 ca-certificates

COPY --from=builder /out/gateway /usr/local/bin/helianthus-gateway
COPY --from=builder /out/helianthus-ebus-adapter-proxy /usr/local/bin/helianthus-ebus-adapter-proxy
COPY --from=vrc-explorer /out/python /opt/helianthus-vrc-explorer
COPY rootfs/ /
