.PHONY: dev prod test migrate setup health logs shell

# ── Development ────────────────────────────────────────────────────────────

## Start development stack and follow logs
dev:
	docker compose up -d
	docker compose logs -f app worker

## Stop all services
down:
	docker compose down

## Rebuild app image (after dependency changes)
build:
	docker compose build app worker

# ── Production ─────────────────────────────────────────────────────────────

## Start production stack
prod:
	docker compose -f docker-compose.prod.yml up -d

## Stop production stack
prod-down:
	docker compose -f docker-compose.prod.yml down

# ── Database ───────────────────────────────────────────────────────────────

## Apply all pending migrations
migrate:
	docker compose exec app alembic upgrade head

## Roll back one migration
migrate-down:
	docker compose exec app alembic downgrade -1

## Show current migration status
migrate-status:
	docker compose exec app alembic current

# ── Testing ────────────────────────────────────────────────────────────────

## Run full test suite
test:
	docker compose exec app pytest tests/ -v

## Run only unit tests
test-unit:
	docker compose exec app pytest tests/unit/ -v

## Run only integration tests
test-integration:
	docker compose exec app pytest tests/integration/ -v

# ── Store Setup ────────────────────────────────────────────────────────────

## Interactive store setup (prompts for credentials)
setup:
	@read -p "Store name:        " name; \
	read -p "Store slug:        " slug; \
	read -p "Shopify domain:    " domain; \
	read -p "Shopify token:     " token; \
	read -p "WhatsApp phone:    " phone; \
	docker compose exec app python -m scripts.setup_store \
		--name "$$name" \
		--slug "$$slug" \
		--shopify-domain "$$domain" \
		--shopify-token "$$token" \
		--whatsapp-phone "$$phone"

## Sync products from Shopify (set STORE_ID in .env first)
sync:
	docker compose exec app python -m scripts.sync_products \
		--store-id $(shell grep ^STORE_ID .env | cut -d= -f2)

## Sync products using mock fixtures (no Shopify credentials needed)
sync-mock:
	docker compose exec app python -m scripts.sync_products \
		--store-id $(shell grep ^STORE_ID .env | cut -d= -f2) \
		--mock

# ── Operations ─────────────────────────────────────────────────────────────

## Run comprehensive health check
health:
	docker compose exec app python -m scripts.health_check

## Follow app and worker logs
logs:
	docker compose logs -f app worker

## Open a shell inside the app container
shell:
	docker compose exec app bash

## Show running containers and their status
ps:
	docker compose ps
