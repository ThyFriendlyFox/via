# Via's image: the toolchain install.sh defines, and Via at the commit it was
# built from. The image workflow (.github/workflows/image.yml) builds it, checks it and publishes it;
# tools/image.py works out its tag from this file, install.sh and requirements.txt. It holds
# Via without the example boards and the site (.dockerignore leaves out examples/ and site/):
# no tool it runs reads them, and a project is mounted on /work.
#
#   docker build -t via .
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/work via workcenter gates .
#
# No window: kicad-cli and the other engines run headless; KiCad's editors are not for a container.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt/workcenters/ee/src
COPY . .

# The 1 definition of the toolchain: the script CI and the cloud environment run, as CI runs it. The
# apt lists and the caches it made are removed in the layer that made them. The image workflow passes
# CI's 2 bounds of the apt step (APT_UPDATE_TIMEOUT=120, APT_DOWNLOAD_TIMEOUT=570); a build that passes
# none, as `docker build .` does, has no bound, as on a person's computer.
ARG APT_UPDATE_TIMEOUT=
ARG APT_DOWNLOAD_TIMEOUT=
RUN REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT="$APT_UPDATE_TIMEOUT" APT_DOWNLOAD_TIMEOUT="$APT_DOWNLOAD_TIMEOUT" ./install.sh \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /root/.cache

# The build's own doctor, then the record of the tag and the tools' versions; a doctor that does not
# pass fails the build, so no such image is published. Then the home any user id may write (KiCad
# stops with `Environment variable HOME is empty`; the CLI needs a home) and the folder a project is
# mounted on. The doctor runs with root's home, so the shared home starts empty.
ARG TOOLCHAIN_TAG=
ARG WORKCENTER_REVISION=
RUN HOME=/root workcenter doctor \
 && HOME=/root python3 tools/image.py record --expect-tag "$TOOLCHAIN_TAG" --revision "$WORKCENTER_REVISION" \
 && rm -rf /root/.cache /root/.config /root/.local \
 && install -d -m 1777 /home/workcenter /work

ENV HOME=/home/workcenter
WORKDIR /work
CMD ["workcenter", "doctor"]
