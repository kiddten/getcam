poetry-lock:
	DOCKER_BUILDKIT=1 BUILDKIT_PROGRESS=plain docker build --target bump-lock --output out .
	cp out/poetry.lock poetry.lock
	rm -rf out

build:
	DOCKER_BUILDKIT=1 BUILDKIT_PROGRESS=plain docker compose build

run:
	docker compose up -d --build && docker compose exec getcam alembic upgrade head

stop:
	docker compose down

run-hub:
	docker compose -f docker-compose-dockerhub.yml up -d --build && docker compose exec getcam alembic upgrade head

stop-hub:
	docker compose -f docker-compose-dockerhub.yml down

update:
	git pull
	docker compose -f docker-compose-dockerhub.yml
	make stop-hub run-hub
