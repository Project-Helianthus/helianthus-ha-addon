# syntax=docker/dockerfile:1.6

ARG BUILD_FROM=ghcr.io/home-assistant/base:3.20
ARG VRCEXPLORER_VERSION=main

FROM --platform=$TARGETPLATFORM golang:1.26-alpine AS builder
ARG TARGETARCH
ARG TARGETVARIANT
ARG EBUSGATEWAY_VERSION=cb2d641b60d4d457aa2d34e7d40eb5e5b7df9627

RUN apk add --no-cache git ca-certificates

ENV CGO_ENABLED=0
ENV GOPRIVATE=github.com/Project-Helianthus/*

RUN --mount=type=secret,id=github_token \
    if [ -f /run/secrets/github_token ]; then \
      git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/"; \
    fi \
 && if [ "${TARGETARCH}" = "arm" ] && [ -n "${TARGETVARIANT}" ]; then export GOARM="${TARGETVARIANT#v}"; fi \
 && GOBIN=/out go install github.com/Project-Helianthus/helianthus-ebusgateway/cmd/gateway@${EBUSGATEWAY_VERSION}

FROM --platform=$BUILDPLATFORM python:3.12-alpine AS vrc-explorer
ARG VRCEXPLORER_VERSION=main

RUN apk add --no-cache git ca-certificates

RUN --mount=type=secret,id=github_token \
    if [ -f /run/secrets/github_token ]; then \
      git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/"; \
    fi \
 && python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir --target /out/python \
    "git+https://github.com/Project-Helianthus/helianthus-vrc-explorer@${VRCEXPLORER_VERSION}"

FROM ${BUILD_FROM}
ARG VRCEXPLORER_VERSION=main

RUN apk add --no-cache python3 ca-certificates

COPY --from=builder /out/gateway /usr/local/bin/helianthus-gateway
COPY --from=vrc-explorer /out/python /opt/helianthus-vrc-explorer
COPY rootfs/ /
RUN chmod +x /usr/share/helianthus/check_runtime_state_wrapper.py
