.PHONY: up down seed logs test api-test
up:
	docker compose up -d

down:
	docker compose down

seed:
	docker compose exec api python seed.py

logs:
	docker compose logs -f api worker web

api-test:
	docker compose exec api pytest -q

test: api-test
