# トラブルシューティング

各項目は **症状** → **原因** → **対処** の 3 行構成。ここに無いエラーは、まず `make logs`、次に `make ps` を確認してください。

---

## スタック起動

### Floci が起動しない / "port 4566 already in use"

- **症状:** `make up` が `Bind for 0.0.0.0:4566 failed: port is already allocated` で失敗、または `floci` が即終了する。
- **原因:** 他の LocalStack/Floci インスタンス（あるいは別の何か）が既にホストのポートを掴んでいる。
- **対処:** `lsof -iTCP:4566 -sTCP:LISTEN`（または `ss -ltnp | grep 4566`）で犯人を特定。kill するか、`.env` で `FLOCI_PORT=4567` に変更して `make down && make up`。

### Floci の healthcheck が `unhealthy` のままになる

- **症状:** `make ps` で API は応答しているのに `floci` が `unhealthy` 表示のまま、依存サービス（`mlflow`）の起動が止まる。
- **原因:** `docker-compose.yml` の healthcheck が `http://localhost:4566/_localstack/health` を curl しているが、一部の Floci ビルドには `curl` が同梱されていない。
- **対処:** `docker-compose.yml` の `floci.healthcheck` ブロックをコメントアウト（ファイル内のインラインコメントでも触れている）し、`make down && make up`。

### `terraform apply` の RDS リソースで `addPersistenceMounts ... SocketException`

- **症状:** Terraform が `aws_db_instance.mlops` のステップで Java 風の `SocketException` や "cannot connect to Docker daemon" を出す。
- **原因:** Floci の RDS は Docker-in-Docker を使い、ホストデーモンに兄弟 Postgres コンテナを起動させる。`/var/run/docker.sock` が `floci` サービスにマウントされていない。
- **対処:** `docker-compose.yml` の `services.floci.volumes` 下に `- /var/run/docker.sock:/var/run/docker.sock` のバインドマウントがあることを確認。`make down && make up` 後に `terraform apply` を再実行。

### `terraform apply` が localhost:4566 への "connection refused" で失敗

- **症状:** `dial tcp 127.0.0.1:4566: connect: connection refused` や `RequestError: send request failed` でエラー。
- **原因:** Floci がまだ healthy になっていない。AWS プロバイダがコンテナ準備完了前に到達しようとした。
- **対処:** `make ps` で `floci` が `running`/`healthy` であることを確認。`make logs`（または `docker compose logs floci`）も併用。落ち着いたら `terraform apply` を再実行。

### WSL2 のボリュームパーミッションエラー（Postgres "could not write file ... Permission denied"）

- **症状:** `mlflow-backend-db` が `chown: changing ownership of '/var/lib/postgresql/data': Operation not permitted` や `FATAL: data directory ... has wrong ownership` で終了。
- **原因:** WSL2 のバインドマウントはデフォルトで root 所有。postgres イメージは UID 999 で実行される。
- **対処:** `sudo chown -R 999:999 ./volumes/mlflow-backend-db`（Floci が文句を言うなら `./volumes/floci-storage` も同様）し、`make down && make up`。

### Jupyter のログイントークンが合わない

- **症状:** `http://localhost:8888` でトークンを要求されるが、`mlops`（または独自 `JUPYTER_TOKEN`）が通らない。
- **原因:** `.env` 編集前にコンテナが起動した、あるいは compose が新しい値を拾っていない。
- **対処:** `make down && make up`（compose は `.env` をコンテナ作成時のみ再読込）。トークンの値は `.env` の `JUPYTER_TOKEN`。

---

## Terraform / Glue

### `terraform apply` の Glue リソースで `InvalidInputException: Resource ARN does not point to a Registry or Schema`

- **症状:** `.tf` ファイルに `aws_glue_catalog_database` や `aws_glue_catalog_table` を書き戻すと、create 成功直後に上記エラーが出る。
- **原因:** Floci の Glue API は Catalog Database の `GetTags` を実装していない。AWS Terraform プロバイダは create 後の read の一部として毎回 `GetTags` を呼ぶ。
- **対処:** Glue は Terraform 管理しない方針。だから `infra/terraform/glue.tf` はコメントのみ。Glue DB と `customer_churn` テーブルは `pipelines/setup_glue.py`（`make glue-setup`）が冪等に作成する。深掘りは `docs/architecture.md` を参照。

### Terraform の state ロックが残る

- **症状:** `terraform apply` が `Error acquiring the state lock` で停止し、`.terraform.tfstate.lock.info` を指している。
- **原因:** 直前の `terraform apply` がローカルファイルロックを解放する前に kill された（Ctrl+C、コンテナ OOM 等）。
- **対処:** `infra/terraform/` で `terraform force-unlock <LOCK-ID>`（ID はエラーメッセージ内に出ている）。他に Terraform プロセスが動いていないと確信できるなら `rm .terraform.tfstate.lock.info`。

---

## パイプライン / データ層

### `psycopg2.OperationalError: connection refused` to `floci-rds-mlops-rds`

- **症状:** `make load-rds`、`make dbt-run`、`make train` が `could not translate host name "floci-rds-mlops-rds"` や同ホストに対する `Connection refused` で失敗。
- **原因:** Floci が RDS 兄弟コンテナを spawn したが、`mlops-net` に接続していない（Floci の RDS サービスは `MAIN_DOCKER_NETWORK` を尊重しない）。
- **対処:** `make rds-attach`（冪等 — `attached` または `already attached` を出力）。RDS リソースの fresh な `terraform apply` の後は毎回必要。

### `load_s3_to_rds.py` が Glue `GetTable` で失敗

- **症状:** `make load-rds` が `glue.get_table(...)` 由来の `EntityNotFoundException: Table customer_churn not found` でエラー。
- **原因:** Glue DB/テーブルが未作成（`make glue-setup` を飛ばした）、または `GLUE_DATABASE_NAME` が存在しない DB に上書きされている。
- **対処:** `make glue-setup`（DB + テーブルを冪等に作成）。あるいはそのまま `make load-rds` を再実行 — ローダは先頭で setup を自動呼び出しする。

### `load_s3_to_rds.py` が `No objects found under s3://raw-data/customer_churn/` で失敗

- **症状:** Glue lookup 成功後の `make load-rds` で、S3 プレフィックスが空という旨のエラー。
- **原因:** `make seed` を飛ばした、または `seed_s3.py` が別プレフィックスにアップロードした。
- **対処:** まず `make seed`。ローダは `s3://${RAW_BUCKET}/customer_churn/` 配下に CSV があることを期待する。

### MLflow に Run はあるがアーティファクトが UI に表示されない

- **症状:** MLflow に Run は出ており、パラメータ/メトリクスもあるが、"Artifacts" タブが空、もしくはモデル読み込みが "no such file" で失敗する。
- **原因:** クライアントプロセスに `MLFLOW_S3_ENDPOINT_URL=http://floci:4566` が設定されておらず、boto3 が本物の AWS を呼びにいっている。
- **対処:** `make train` 経由で実行（`dbt` サービスは `docker-compose.yml` で設定済み）。Notebook の場合は `.env` 編集後にカーネルを再起動して新しい env を Python プロセスに反映させる。

### `make dbt-run` を繰り返してもデータが古いまま

- **症状:** dbt はクリーンに走るが、`marts.customer_features` に直前ロードした新規行が反映されていない。
- **原因:** `customer_features` は `table` マテリアライゼーションで毎回再ビルドされるが、*ソース* は実行時に読まれる。`make load-rds` を再実行し忘れていれば dbt は同じソースを読む。staging の `view` は何もキャッシュしないので常に最新ソースを反映する（こちらの方向性で混乱を招くこともある）。
- **対処:** `make load-rds && make dbt-run`。dbt にクリーンスレートからの drop + rebuild を強制するには `docker compose run --rm dbt dbt run --full-refresh`。

---

## Known issues（ここでは修正しない — トラッキングして適切なソースで対応）

ビルド中にフラグされた既知の問題。実在するが、docs-writer としては **そのまま** 残す。修正は該当のソースファイルで行う。

### dbt-core が 1.10.x 系ではなく 1.11.9 に解決される

- **症状:** dbt コンテナ内で `pip show dbt-core` を実行すると、`dbt/requirements.txt` が `dbt-postgres==1.10.0` をピン留めしているにもかかわらず `1.11.9` と表示される。
- **原因:** dbt-postgres 1.10.0 は推移的に dbt-core 1.11.x（protobuf 6.x）を要求する dbt-adapters バージョンに依存している。古い dbt-core 1.10 系は互換性なし。`dbt/requirements.txt` のコメント参照。
- **対処:** 不要 — 意図的。dbt-core を 1.10 にピン留めしたい場合は、dbt-postgres とアダプタも合わせてダウングレードする必要がある。

### `tenure = 0` の行で `total_charges` が NULL

- **症状:** `marts.customer_features.total_charges`（および派生の `charges_per_month_of_tenure`）が新規顧客では NULL。`total_charges` に `not_null` テストを追加すると失敗する。
- **原因:** Telco-churn CSV は `tenure=0` の顧客に対し空白のみの `total_charges` を出力する。staging の `nullif(trim(...), '')::numeric` が正しく NULL を生成。marts の spend-ratio カラムは `tenure=0` を明示的にガードしている。
- **対処:** 不要 — 想定動作。`dbt/models/staging/schema.yml` は意図的に `total_charges` に `not_null` を課していない。下流（`train.py`）は `SimpleImputer(strategy="median")` で補完。

### boolean `churn` の `accepted_values` テストには `quote: false` が必要

- **症状:** `stg_customer_churn.churn` の `accepted_values` テストを `values: ['true', 'false']` で書くと `dbt test` が失敗。
- **原因:** dbt のデフォルトでは `accepted_values` は値を文字列としてクォートするが、`churn` は staging で coerce された後 Postgres の `boolean`。
- **対処:** 既に `dbt/models/staging/schema.yml` で適用済み: `accepted_values: arguments: { values: [true, false], quote: false }`。クォート文字列に「戻し」たりしないこと。

---

## あると便利なコマンドスニペット

```bash
# 1 サービスのログを追跡
docker compose logs -f floci

# ネットワーク内から Floci RDS に psql で接続
docker compose run --rm dbt psql -h floci-rds-mlops-rds -p 5432 -U mlops -d mlops

# dbt コンテナ内でシェルを開く
docker compose run --rm dbt bash

# dbt をクリーン再構築
docker compose run --rm dbt dbt run --full-refresh

# ホストから出ずに S3 の中身を確認
docker compose run --rm dbt python -c "import boto3, os; \
print(boto3.client('s3', endpoint_url='http://floci:4566').list_buckets())"

# Glue DB + テーブルを最初から再作成（冪等）
make glue-setup
```
