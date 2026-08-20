# syntax=docker/dockerfile:1.6

ARG BUILD_FROM=ghcr.io/home-assistant/base:3.20
ARG VRCEXPLORER_VERSION=v0.5.1
ARG BUILD_VERSION

FROM --platform=$TARGETPLATFORM golang:1.26.2-alpine AS builder
ARG TARGETARCH
ARG TARGETVARIANT
ARG BUILD_VERSION
ARG EBUSGATEWAY_VERSION=a759efd7f72a099288f1fc2b7cf20236d37cfa0b

RUN apk add --no-cache git ca-certificates
COPY build/verify-no-secret.sh /usr/local/bin/verify-no-secret

ENV CGO_ENABLED=0
ENV GOPRIVATE=github.com/Project-Helianthus/*

RUN --mount=type=secret,id=github_token \
    set -eu; \
    github_token_value=""; \
    if [ -f /run/secrets/github_token ]; then \
      github_token_value="$(cat /run/secrets/github_token)"; \
      export GIT_CONFIG_COUNT=1; \
      export GIT_CONFIG_KEY_0="url.https://x-access-token:${github_token_value}@github.com/.insteadOf"; \
      export GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi; \
    git clone --no-checkout https://github.com/Project-Helianthus/helianthus-ebusgateway /src; \
    cd /src; \
    git checkout --detach "${EBUSGATEWAY_VERSION}"; \
    test "$(git rev-parse HEAD)" = "${EBUSGATEWAY_VERSION}"; \
    test -n "${BUILD_VERSION}"; \
    test -z "$(git status --porcelain=v1 --untracked-files=all)"; \
    if [ "${TARGETARCH}" = "arm" ] && [ -n "${TARGETVARIANT}" ]; then export GOARM="${TARGETVARIANT#v}"; fi; \
    GOWORK=off GOENV=off GOTOOLCHAIN=local GOFLAGS=-mod=readonly \
      GOMODCACHE=/tmp/helianthus-gomod GOCACHE=/tmp/helianthus-gocache \
      go build -trimpath -buildvcs=true \
      -ldflags "-X main.buildVersion=${BUILD_VERSION} -X main.buildID=${EBUSGATEWAY_VERSION}" \
      -o /out/gateway ./cmd/gateway; \
    if [ -n "${github_token_value}" ]; then \
      sh /usr/local/bin/verify-no-secret "${github_token_value}" /root /src /out /tmp /go; \
    fi

FROM --platform=$BUILDPLATFORM python:3.12-alpine AS vrc-explorer
ARG VRCEXPLORER_VERSION=v0.5.1

RUN apk add --no-cache git ca-certificates
COPY build/verify-no-secret.sh /usr/local/bin/verify-no-secret

RUN --mount=type=secret,id=github_token \
    set -eu; \
    github_token_value=""; \
    if [ -f /run/secrets/github_token ]; then \
      github_token_value="$(cat /run/secrets/github_token)"; \
      export GIT_CONFIG_COUNT=1; \
      export GIT_CONFIG_KEY_0="url.https://x-access-token:${github_token_value}@github.com/.insteadOf"; \
      export GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi; \
    python -m pip install --no-cache-dir --upgrade pip; \
    python -m pip install --no-cache-dir --target /out/python \
      "git+https://github.com/Project-Helianthus/helianthus-vrc-explorer@${VRCEXPLORER_VERSION}"; \
    if [ -n "${github_token_value}" ]; then \
      sh /usr/local/bin/verify-no-secret "${github_token_value}" /root /out /tmp /usr/local; \
    fi

FROM ${BUILD_FROM}
ARG VRCEXPLORER_VERSION=v0.5.1

RUN apk add --no-cache python3 ca-certificates

COPY --from=builder /out/gateway /usr/local/bin/helianthus-gateway
COPY --from=vrc-explorer /out/python /opt/helianthus-vrc-explorer
COPY rootfs/ /
RUN chmod +x /usr/share/helianthus/check_runtime_state_wrapper.py \
    /usr/share/helianthus/modbus_runtime_guard.py
