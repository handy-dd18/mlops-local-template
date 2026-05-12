# アーキテクチャと設計判断

このドキュメントはスタックの構造の **理由（why）** を記録します。README は「何が動いていてどう使うか」を扱い、ここは将来のコントリビュータがトレードオフを再導出せずに済むようにするためのページです。

---

## MLflow サーバは 1 台、DS とエンジニアで共有

両トラックとも同じ MLflow サーバ（`http://mlflow:5000`）にログします。分離は **Experiment 名** で行います:

- `notebook-exploration` — `notebooks/01_explore.ipynb` で設定。DS が Jupyter 上で行うアドホックな作業全般。
- `pipeline-production` — `pipelines/train.py` で設定。エンジニアパイプラインから出てきたもの全般。

なぜ 2 台ではなく 1 台にしたか:

- 単一の MLflow UI は、このテンプレートにおける事実上の「ホームページ」に最も近い存在です。2 台に分けるとその位置づけが希薄になります。
- DS とエンジニアの境界はワークフロー上の区別であって、デプロイの区別ではありません。DS の Notebook がパイプラインに昇格する場合、履歴はそのまま引き継がれるべきで、別サーバから別サーバへ Experiment を「移送」するのは余計な作業になります。
- 運用がシンプル: Postgres バックエンド 1 つ、アーティファクトバケット 1 つ、ポートマッピング 1 セット。

守るべき規約: **常に `mlflow.set_experiment(...)` をコード内で明示的に呼ぶ。** デフォルトの Experiment は「設定し忘れた人のための受け皿」として空のまま残してください。

---

## MLflow バックエンド DB は Floci エミュレートの RDS とは別

スタック内に Postgres インスタンスが 2 つあります:

1. `mlflow-backend-db` — `mlops-net` 上の `postgres:16-alpine`、MLflow 内部ストア（`MLFLOW_BACKEND_STORE_URI`）を保持。コンテナ内で完結し、ユーザコードからは触れません。
2. Floci が spawn した RDS 兄弟コンテナ（`floci-rds-mlops-rds`） — `pipelines/load_s3_to_rds.py`、dbt、`pipelines/train.py` が話す相手。

なぜ Floci RDS に統合しないか:

- **障害の隔離。** スタックで最も壊れやすいのは Floci です（LocalStack 系エミュレータは本物の Postgres イメージよりも不安定で、特に RDS サービスは Docker-in-Docker — 後述）。その側が壊れても MLflow は稼働し続け、デバッグ中も過去の Run を閲覧できます。
- **ライフサイクルの独立性。** `make tf-destroy` と `make nuke` は Floci 側を定期的に消します。MLflow が同じ DB に乗っていると、毎回のリセットで Run 履歴も消えます。
- **ポート衛生。** MLflow の DB はホストから到達可能である必要が一切ありません。Floci RDS は必要です。別コンテナに分けることでポートマッピングの意図が明示されます。

コスト: 追加で約 50 MB の RAM。割に合います。

---

## Glue は Terraform 管理「しない」

`infra/terraform/glue.tf` は意図的に空（先頭コメントのみ）です。Glue Database と `customer_churn` テーブルは `pipelines/setup_glue.py` が boto3 で作成し、`make glue-setup` 経由で呼び出します（また `pipelines/load_s3_to_rds.py` の先頭からも自動呼び出しされ、ローダだけで完結するようにしています）。

なぜ Glue を Terraform 外に出したか:

- Floci の Glue API は Catalog Database の `GetTags` を **実装していません**。`InvalidInputException: Resource ARN does not point to a Registry or Schema` を返します。
- AWS Terraform プロバイダは `aws_glue_catalog_database` / `aws_glue_catalog_table` の create 後の read の一部として毎回 `GetTags` を呼ぶため、create 成功直後にリソースがエラーになります。この read を無効化するプロバイダフラグは存在しません。
- boto3 は `GetTags` を自動的には呼ばないので、素朴な `create_database` / `create_table` 呼び出しは Floci 相手にもクリーンに通ります。

帰結と規約:

- Glue テーブルは依然として raw レイヤの **正式なスキーマ定義** です。`pipelines/load_s3_to_rds.py` は実行時に `glue.get_table(...)` を呼んでカラムリストと S3 ロケーションを取得します — カラム追加は `pipelines/setup_glue.py` の `COLUMNS` リストを編集して `make glue-setup` を再実行すれば、ローダ側は自動で拾います。
- 全カラムは `string` 型です。OpenCSVSerde が非文字列の Glue カラムをサポートしないためです。型キャストは `dbt/models/staging/stg_customer_churn.sql` で下流に実施します。
- `pipelines/setup_glue.py` は冪等: DB の `AlreadyExistsException` をキャッチし、テーブルはスキーマ変更を反映するために強制再作成します。
- 本物の AWS を相手にする場合は、このスクリプトをそのまま残しても Terraform に書き戻しても構いません。Floci の外なら両方動きます。

---

## dbt は `postgres` アダプタを使う（Glue/Athena アダプタではない）

dbt のターゲットは **常に RDS Postgres** です。staging のビューと marts のテーブルがマテリアライズされる場所であり、`train.py` の読み込み先でもあります。Glue は raw レイヤのメタデータを保持するのみで、dbt から直接クエリすることはありません。

理由:

- dbt-postgres は成熟していて高速で、追加サービスなしに 1 コンテナで動きます。dbt-glue / dbt-athena は Spark/Athena ランタイムを引き連れてきますが、Floci ではエミュレートしきれません。
- S3 → RDS のロードは 1 つの安価なスクリプト（`load_s3_to_rds.py`）で済みます。一度ロードして以降は dbt に Postgres を操作させる方が、メタストア経由で CSV を読ませるよりはるかにシンプルです。
- 現実的な小規模チーム構成を反映しています: データはオブジェクトストレージに着地し、データウェアハウスに取り込まれ、dbt がウェアハウスをモデル化する。

正式なスキーマは Glue にあるが dbt は Postgres を読む、という構図において、ローダスクリプトが両者の **橋渡し** です。小さく愚直に保ってください。

---

## Floci には `/var/run/docker.sock` のマウントが必要（RDS の Docker-in-Docker）

`docker-compose.yml` は `floci` サービスに `/var/run/docker.sock` をマウントしています。一見ぎょっとしますが、必須です:

- Floci の RDS サービスは Postgres をプロセス内で動かしません。代わりに Terraform が `CreateDBInstance` を呼ぶと、Floci は（マウントしたソケット経由で）ホストの Docker デーモンに `floci-rds-<instance-id>` という名前の **兄弟** `postgres:16` コンテナを起動するよう依頼します。
- ソケットマウントが無いと、`terraform apply` の RDS リソースで `addPersistenceMounts ... SocketException` が出て失敗します。
- Floci コンテナには `MAIN_DOCKER_NETWORK=mlops-local-template_mlops-net` を設定しており、spawn する RDS 兄弟をどのユーザ定義ブリッジネットワークに置くかを伝えています。実際には Floci は一部の子サービスに対しては自動でこれを行いますが、RDS には行わないため `make rds-attach` が必要です（後述）。

これは信頼に関するトレードオフです: `floci` 内で動くものはホストの Docker API に完全にアクセスできます。単一ユーザのローカルテンプレートでは受容可能ですが、それ以外の用途では受け入れられません。

---

## `make rds-attach` が存在する理由 — Floci が RDS 子を自動接続しないため

`terraform apply` が完了したあと、spawn された `floci-rds-mlops-rds` コンテナは起動していますが `mlops-net` 上には **いません**。Floci はデフォルトブリッジにしか接続してくれません。その結果、`dbt` やパイプラインのコンテナはホスト名を解決できません。

`make rds-attach` は 1 行 target で、`docker network connect mlops-local-template_mlops-net floci-rds-mlops-rds` を実行します（冪等 — 2 回目以降は `already attached` を出力）。RDS リソースの fresh な `terraform apply` のあとは毎回実行する必要があります。これ以降、dbt は `floci-rds-mlops-rds:5432`（**コンテナのネイティブ 5432**。Floci ゲートウェイポートではない）に接続します。

このスタックで最も意外な仕様の単一の箇所です。実行しないと、Postgres に触る target はすべて "connection refused" で落ちます。

---

## バインドマウント、Docker named volume ではなく `./volumes/`

すべての永続状態はホストの `./volumes/` 配下にバインドマウントしています:

- `./volumes/mlflow-backend-db/` — MLflow の Postgres データディレクトリ。
- `./volumes/floci-storage/` — Floci の S3/Glue/RDS 状態（spawn される RDS コンテナは内部で自前の pgdata を管理するので除外）。

`docker volume create ...` ではなくバインドマウントにした理由:

- **DS にとっての透明性。** データサイエンティストは `ls ./volumes/floci-storage/` で実ファイルを見られます。named volume は中身を `/var/lib/docker/volumes/` に隠してしまい、macOS / Windows / WSL2 上では事実上アクセス不能です。
- **手作業でのリセットが容易。** `rm -rf ./volumes/floci-storage` は `docker volume rm <hash>` よりずっとわかりやすい操作です。
- **`make nuke` はバインドマウントを消しません**（Docker 管理ボリュームのみ削除）。これは意図的 — 明示的な削除を別の意識的なステップとして残しています。

代償は WSL2 のパーミッション問題（`docs/troubleshooting.md` 参照）。可視性と引き換えに許容しています。

---

## `dbt` サービスは Compose の `tools` プロファイル

`docker-compose.yml` で `dbt` サービスは `profiles: [tools]` の背後にあります。これにより `make up`（実体は `docker compose up -d`）では `dbt` は **起動しません**。それを必要とする target — `make glue-setup`、`make seed`、`make load-rds`、`make dbt-run`、`make dbt-test`、`make train` — はすべて `docker compose run --rm dbt ...` を使い、ワンショットコンテナとして起動します。

これにより「常時起動」のフットプリントは 4 コンテナ（Jupyter、MLflow、MLflow の DB、Floci）に抑えられ、6 つ目のアイドル Python プロセスを避けられます。また、永続稼働の UI を中断せずに dbt イメージを再ビルドできるという安全性も得られます。

---

## スコープ外（意図的に）

このテンプレートは小さく保つ方針です。以下は **含めず**、今後も追加しません:

- **CI / CD。** GitHub Actions もテストオーケストレーションもなし。すべてローカルで完結することが目的そのもの。
- **SaaS 連携。** 本物の AWS、マネージド MLflow、Snowflake/Databricks 等は無し。必要ならフォークしてください。
- **マルチノード / 分散学習。** シングルプロセスの scikit-learn が上限。
- **GPU 対応。** すべて CPU のみのイメージ。
- **認証 / マルチユーザ MLflow。** MLflow はシングルユーザ、認証なし。
- **本番品質の Postgres チューニング、バックアップ、レプリケーション。** 両 Postgres インスタンスとも初期設定で稼働。
- **スキーママイグレーションツール。** `load_s3_to_rds.py` は `if_exists='replace'` で動きます。raw は S3 から再生可能で、その下流はすべて dbt が扱うためです。

ここに挙げた項目を欲しくなった時点で、プロジェクトはこのテンプレートを「卒業」する段階にあります — コピーして独立させてください。
