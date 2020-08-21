ARG DOCKER_IMAGE_VERSION
ARG PLATFORM
FROM registry.gitlab.com/buildstream/buildstream-docker-images/testsuite-$PLATFORM-$DOCKER_IMAGE_VERSION AS base

##
# Docker stages for building test containers
##
FROM base as test_setup

ADD . /buildstream
WORKDIR /buildstream
RUN useradd -Um buildstream
RUN chown -R buildstream:buildstream .

ENTRYPOINT ["su", "buildstream", "-c"]

FROM test_setup as randomised_tests

ARG INTEGRATION_CACHE
RUN mkdir -p ${INTEGRATION_CACHE}

ENTRYPOINT ["su", "buildstream", "-c"]

FROM test_setup as fedora_missing_deps

RUN dnf mark install fuse-libs systemd-udev
RUN dnf erase -y bubblewrap ostree

ENTRYPOINT ["su", "buildstream", "-c"]

##
# Docker stages for building integration overnight tests
##
FROM base as build_env

ARG BST_EXT_REF
ARG FD_SDK_REF

RUN mkdir -p "${HOME}/.config"
RUN { \
    echo "scheduler:"; \
    echo "  fetchers: 2"; \
}  >  "${HOME}/.config/buildstream.conf"
RUN dnf install -y ostree

ADD . /buildstream
WORKDIR /buildstream
RUN pip3 install \
      -r requirements/requirements.txt \
      . \
      git+https://gitlab.com/buildstream/bst-plugins-experimental.git@${BST_EXT_REF}#egg=bst_plugins_experimental[cargo]
RUN git clone https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git
RUN git -C freedesktop-sdk checkout ${FD_SDK_REF}

FROM build_env as cache_setup
RUN { \
    echo "# Get a lot of output in case of errors"; \
    echo "logging:"; \
    echo "  error-lines: 80"; \
    echo "#"; \
    echo "# Artifacts"; \
    echo "#"; \
    echo "artifacts:"; \
    echo "- url: https://cache-test.buildstream.build:11002"; \
    echo "  client-cert: $OVERNIGHT_CACHE_PUSH_CERT"; \ 
    echo "  client-key: $OVERNIGHT_CACHE_PUSH_KEY"; \
    echo "  push: true"; \
} > ~/.config/buildstream.conf

FROM build_env as no_cache_setup
RUN sed -i '/artifacts:/,+1 d' freedesktop-sdk/project.conf