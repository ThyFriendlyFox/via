# The EE Workcenter's image: the toolchain install.sh defines, and the workcenter at the commit it was
# built from. The image workflow (.github/workflows/image.yml) builds it, checks it and publishes it;
# tools/image.py works out its tag from this file, install.sh and requirements.txt. It holds the
# workcenter without the example boards and the site (.dockerignore leaves out examples/ and site/):
# no tool it runs reads them, and a project is mounted on /work.
#
#   docker build -t ee-workcenter .
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/work ee-workcenter workcenter gates .
#
# No window: kicad-cli and the other engines run headless; KiCad's editors are not for a container.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt/workcenters/ee/src
COPY . .

# The 1 definition of the toolchain: the script CI and the cloud environment run, as CI runs it. The
# apt lists and the caches it made are removed in the layer that made them.
RUN REQUIRE_FREEROUTING=1 ./install.sh \
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
