# syntax=docker/dockerfile:1.6

ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19

FROM --platform=$BUILDPLATFORM golang:1.22-alpine AS builder
ARG TARGETOS=linux
ARG TARGETARCH=amd64
ARG TARGETVARIANT=
ARG EBUSGATEWAY_VERSION=main

RUN apk add --no-cache git ca-certificates

ENV CGO_ENABLED=0
ENV GOPRIVATE=github.com/d3vi1/*

RUN --mount=type=secret,id=github_token \
    if [ -f /run/secrets/github_token ]; then \
      git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/"; \
    fi \
 && GOBIN=/out GOOS=$TARGETOS GOARCH=$TARGETARCH GOARM=${TARGETVARIANT#v} \
    go install github.com/d3vi1/helianthus-ebusgateway/cmd/gateway@${EBUSGATEWAY_VERSION}

FROM ${BUILD_FROM}

COPY --from=builder /out/gateway /usr/local/bin/helianthus-gateway
COPY rootfs/ /
