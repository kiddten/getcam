FROM python:3.8

RUN mkdir -p /tmp/distr && \
    cd /tmp/distr && \
    wget https://download.imagemagick.org/ImageMagick/download/releases/ImageMagick-7.0.11-2.tar.xz && \
    tar xvf ImageMagick-7.0.11-2.tar.xz && \
    cd ImageMagick-7.0.11-2 && \
    ./configure --enable-shared=yes --disable-static --without-perl && \
    make && \
    make install && \
    ldconfig /usr/local/lib && \
    cd /tmp && \
    rm -rf distr

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

# Install required packages
RUN apt-get update && apt-get install -y fontconfig

# Create a directory in the container to store the fonts
RUN mkdir -p /usr/local/share/fonts/Ubuntu

# Copy all font files from the local "Ubuntu" folder to the container
COPY Ubuntu/* /usr/local/share/fonts/

# Refresh the font cache
RUN fc-cache -f -v

ENV PYTHONUNBUFFERED=1 \
    # pip
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    \
    # Poetry
    # https://python-poetry.org/docs/configuration/#using-environment-variables
    POETRY_VERSION=1.7.1 \
    # make poetry install to this location
    POETRY_HOME="/opt/poetry" \
    # do not ask any interactive question
    POETRY_NO_INTERACTION=1 \
    # never create virtual environment automaticly, only use env prepared by us
    POETRY_VIRTUALENVS_CREATE=false \
    \
    # this is where our requirements + virtual environment will live
    VIRTUAL_ENV="/venv"

# prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VIRTUAL_ENV/bin:$PATH"

# prepare virtual env
RUN python -m venv $VIRTUAL_ENV

# working directory and Python path
WORKDIR /app
ENV PYTHONPATH="/app:$PYTHONPATH"

RUN --mount=type=cache,target=/root/.cache \
    curl -sSL https://install.python-poetry.org | python -

# Copy poetry files
#COPY pyproject.toml poetry.lock ./
COPY pyproject.toml ./

# Install project dependencies
RUN --mount=type=cache,target=/root/.cache \
    poetry install --no-root --only main

COPY . .

CMD ["poetry", "run", "python", "-m", "shot.shot", "run"]
