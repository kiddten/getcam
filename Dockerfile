FROM python:3.8 as base

# Install curl and dependencies
RUN apt-get update \
    && apt-get install -y curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y software-properties-common \
    && apt-get install -y python3-launchpadlib \
    && add-apt-repository -y ppa:mc3man/trusty-media \
    && apt-get dist-upgrade -y \
    && apt-get install -y ffmpeg

RUN mkdir -p /tmp/distr \
    && cd /tmp/distr \
    && wget https://download.imagemagick.org/ImageMagick/download/releases/ImageMagick-7.0.11-2.tar.xz \
    && tar xvf ImageMagick-7.0.11-2.tar.xz \
    && cd ImageMagick-7.0.11-2 \
    && ./configure --enable-shared=yes --disable-static --without-perl \
    && make \
    && make install \
    && ldconfig /usr/local/lib \
    && cd /tmp \
    && rm -rf distr

# Install required packages
RUN apt-get update && apt-get install -y fontconfig

# Create a directory in the container to store the fonts
RUN mkdir -p /usr/local/share/fonts/Ubuntu

# Copy all font files from the local "Ubuntu" folder to the container
COPY Ubuntu/* /usr/local/share/fonts/

# Refresh the font cache
RUN fc-cache -f -v

ENV \
  # python:
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PYTHONDONTWRITEBYTECODE=1 \
  # pip:
  PIP_NO_CACHE_DIR=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PIP_DEFAULT_TIMEOUT=100 \
  PIP_ROOT_USER_ACTION=ignore \
  # poetry:
  POETRY_VERSION=1.7.1 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_CREATE=false \
  POETRY_HOME='/usr/local'

RUN \
  # Installing `poetry` package manager:
  # https://github.com/python-poetry/poetry
  curl -sSL 'https://install.python-poetry.org' | python - \
  && poetry --version

WORKDIR /app
ENV TZ="Europe/Moscow"

FROM base as bump-lock-prepare
COPY ./pyproject.toml /app/
RUN poetry lock

FROM scratch AS bump-lock
COPY --from=bump-lock-prepare /app/poetry.lock .


FROM base as build
COPY pyproject.toml poetry.lock /app/

# Install project dependencies
RUN poetry version \
  # Install deps:
  && poetry run pip install -U pip \
  && poetry install -vvv --no-interaction --no-ansi

COPY . /app

# https://stackoverflow.com/a/76747791/3990145
RUN poetry install --no-interaction --no-ansi

CMD ["poetry", "run", "python", "-m", "shot.shot", "run"]
