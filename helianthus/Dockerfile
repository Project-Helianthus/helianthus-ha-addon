# syntax=docker/dockerfile:1.6

ARG BUILD_FROM=ghcr.io/home-assistant/base:3.20
ARG VRCEXPLORER_VERSION=v0.5.1

FROM --platform=$TARGETPLATFORM golang:1.26.2-alpine AS builder
ARG TARGETARCH
ARG TARGETVARIANT
ARG EBUSGATEWAY_VERSION=eeddc945b88b2b63bfdfc3514cd4db0485a0b886

RUN apk add --no-cache git ca-certificates

ENV CGO_ENABLED=0
ENV GOPRIVATE=github.com/Project-Helianthus/*

RUN --mount=type=secret,id=github_token \
    set -eu; \
    if [ -f /run/secrets/github_token ]; then \
      export GIT_CONFIG_COUNT=1; \
      export GIT_CONFIG_KEY_0="url.https://$(cat /run/secrets/github_token)@github.com/.insteadOf"; \
      export GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi; \
    git clone --no-checkout https://github.com/Project-Helianthus/helianthus-ebusgateway /src; \
    cd /src; \
    git checkout --detach "${EBUSGATEWAY_VERSION}"; \
    test "$(git rev-parse HEAD)" = "${EBUSGATEWAY_VERSION}"; \
    test -z "$(git status --porcelain=v1 --untracked-files=all)"; \
    if [ "${TARGETARCH}" = "arm" ] && [ -n "${TARGETVARIANT}" ]; then export GOARM="${TARGETVARIANT#v}"; fi; \
    GOWORK=off GOENV=off GOTOOLCHAIN=local GOFLAGS=-mod=readonly \
      go build -trimpath -buildvcs=true -o /out/gateway ./cmd/gateway

FROM --platform=$BUILDPLATFORM python:3.12-alpine AS vrc-explorer
ARG VRCEXPLORER_VERSION=v0.5.1

RUN apk add --no-cache git ca-certificates

RUN --mount=type=secret,id=github_token \
    if [ -f /run/secrets/github_token ]; then \
      git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/"; \
    fi \
 && python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir --target /out/python \
    "git+https://github.com/Project-Helianthus/helianthus-vrc-explorer@${VRCEXPLORER_VERSION}"

FROM ${BUILD_FROM}
ARG VRCEXPLORER_VERSION=v0.5.1

RUN apk add --no-cache python3 ca-certificates

COPY --from=builder /out/gateway /usr/local/bin/helianthus-gateway
COPY --from=vrc-explorer /out/python /opt/helianthus-vrc-explorer
COPY rootfs/ /
RUN chmod +x /usr/share/helianthus/check_runtime_state_wrapper.py
