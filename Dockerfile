ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

COPY rootfs/ /

CMD ["/bin/bash", "-c", "echo \"Helianthus HA add-on placeholder\"; sleep infinity"]
