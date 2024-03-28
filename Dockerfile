FROM python:3.8 as base

ARG FONTS_PATH=/usr/local/share/fonts/Ubuntu
ARG FONTS_URL=https://github.com/kiddten/getcam/raw/master/fonts/Ubuntu.zip

RUN apt-get update && apt-get install -y \
    curl \
    software-properties-common \
    python3-launchpadlib \
    fontconfig \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p $FONTS_PATH  \
    && wget -q -O $FONTS_PATH/tmp.zip $FONTS_URL  \
    && unzip $FONTS_PATH/tmp.zip -d $FONTS_PATH  \
    && rm $FONTS_PATH/tmp.zip \
    && fc-cache -f -v \
    && sed -i 's/none/read,write/g' /etc/ImageMagick-6/policy.xml

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
