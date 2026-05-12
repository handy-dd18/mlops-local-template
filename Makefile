# MLOps local template — orchestration targets.
# Run `make` (or `make help`) for the target list.

SHELL := /bin/bash
COMPOSE := docker compose
TF_DIR := infra/terraform

.DEFAULT_GOAL := help

.PHONY: help up down logs ps nuke tf-init tf-apply tf-destroy rds-attach glue-setup seed load-rds dbt-run dbt-test train generate-data

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the default stack (jupyter, mlflow, mlflow-backend-db, floci)
	@echo ">> docker compose up -d"
	$(COMPOSE) up -d

down: ## Stop the stack (keeps volumes)
	@echo ">> docker compose down"
	$(COMPOSE) down

logs: ## Tail logs from all services
	@echo ">> docker compose logs -f --tail=200"
	$(COMPOSE) logs -f --tail=200

ps: ## Show status of all services
	@echo ">> docker compose ps"
	$(COMPOSE) ps

nuke: ## Stop stack and remove named volumes (does NOT delete ./volumes/)
	@echo ">> docker compose down -v"
	@echo "WARNING: this removes Docker-managed volumes. Local bind mounts under ./volumes/ are NOT touched — delete them manually if desired."
	$(COMPOSE) down -v

tf-init: ## terraform init (inside infra/terraform)
	@echo ">> terraform init ($(TF_DIR))"
	cd $(TF_DIR) && terraform init

tf-apply: ## terraform apply -auto-approve
	@echo ">> terraform apply -auto-approve ($(TF_DIR))"
	cd $(TF_DIR) && terraform apply -auto-approve

tf-destroy: ## terraform destroy -auto-approve
	@echo ">> terraform destroy -auto-approve ($(TF_DIR))"
	cd $(TF_DIR) && terraform destroy -auto-approve

rds-attach: ## Attach the Floci-spawned RDS container to mlops-net (idempotent; run after tf-apply)
	@echo ">> docker network connect mlops-local-template_mlops-net floci-rds-mlops-rds"
	@docker network connect mlops-local-template_mlops-net floci-rds-mlops-rds 2>/dev/null && echo "attached" || echo "already attached or container missing"

glue-setup: ## Create the Glue Catalog DB + customer_churn table via boto3 (idempotent)
	@echo ">> setup_glue.py via dbt container"
	$(COMPOSE) run --rm dbt python /workspace/pipelines/setup_glue.py

seed: ## Upload local CSVs to Floci S3 (requires pipelines/seed_s3.py)
	@echo ">> seed_s3.py via dbt container"
	$(COMPOSE) run --rm dbt python /workspace/pipelines/seed_s3.py

load-rds: ## Move S3 data into Floci RDS (requires pipelines/load_s3_to_rds.py)
	@echo ">> load_s3_to_rds.py via dbt container"
	$(COMPOSE) run --rm dbt python /workspace/pipelines/load_s3_to_rds.py

dbt-run: ## Run dbt models against Floci RDS
	@echo ">> dbt run"
	$(COMPOSE) run --rm dbt dbt run

dbt-test: ## Run dbt tests
	@echo ">> dbt test"
	$(COMPOSE) run --rm dbt dbt test

train: ## Run the training pipeline (requires pipelines/train.py)
	@echo ">> train.py via dbt container"
	$(COMPOSE) run --rm dbt python /workspace/pipelines/train.py

generate-data: ## Generate sample CSVs into data/raw/
	@echo ">> generate_sample_data.py via jupyter container"
	$(COMPOSE) run --rm jupyter python /home/jovyan/work/scripts/generate_sample_data.py
