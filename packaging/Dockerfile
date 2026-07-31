# Runtime image: the self-contained `gyza` onedir binary on a common,
# conservative base (Ubuntu 22.04 — the baseline defense/enterprise
# evaluators run). The universal on-ramp for anyone without a Linux box:
#
#   docker run --rm ghcr.io/aaronamire/gyza demo
#
# Build it from a staged context (the repo .dockerignore excludes dist/):
#   packaging/build-runtime-image.sh gyza-runtime
# It expects the onedir tree at ./dist/gyza (produce it with
# packaging/Dockerfile.build, then `docker cp` the tree out). Kept as a
# separate, tiny runtime image so the shipped container carries only the
# binary + bubblewrap, not the whole build toolchain.
#
# ENFORCEMENT UNDER DOCKER (measured, not assumed):
#   * DEFAULT `docker run … gyza demo` => DISCLOSED. Docker's default
#     seccomp blocks unprivileged user namespaces, so bubblewrap cannot
#     create one; the demo's functional probe detects that and runs the
#     honest disclosed path (backend=none), it does NOT crash.
#   * OS-ENFORCED containment needs userns unblocked:
#       docker run --rm --security-opt seccomp=unconfined \
#                  --security-opt systempaths=unconfined \
#                  ghcr.io/aaronamire/gyza demo
#     => ENFORCED (backend=bubblewrap).
# The demo always states, on screen, which mode it actually ran in.
FROM ubuntu:22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The onedir tree (carries its own Python + native deps).
COPY dist/gyza /opt/gyza
RUN ln -sfn /opt/gyza/gyza /usr/local/bin/gyza \
    && gyza --help >/dev/null

# Run as an unprivileged user — bubblewrap's own containment does NOT need
# root, and a non-root default is the honest posture for a containment tool.
RUN useradd --create-home --uid 10001 gyza
USER gyza
WORKDIR /home/gyza

ENTRYPOINT ["gyza"]
CMD ["demo"]
