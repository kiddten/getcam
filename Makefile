poetry-lock:
	DOCKER_BUILDKIT=1 docker build --target bump-lock --output out .
	cp out/poetry.lock poetry.lock

build:
	DOCKER_BUILDKIT=1 BUILDKIT_PROGRESS=plain docker compose build
run:
	docker compose up -d --build && docker compose exec getcam alembic upgrade head
