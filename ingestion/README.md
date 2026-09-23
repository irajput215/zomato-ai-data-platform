# Ingestion — local CSVs to the S3 data lake

Two scripts, one job each.

```
data/raw/<table>/<table>.csv   ->   s3://<bucket>/raw/<table>/<table>.csv
```

The local directory tree mirrors the lake layout exactly, so there are no naming
rules to remember — whatever is under `data/raw/` lands under `raw/` at the same
relative path.

```bash
pip install -r ingestion/requirements.txt

# what would happen, touching nothing
python ingestion/upload_to_s3.py --dry-run

# upload everything
python ingestion/upload_to_s3.py

# just the two biggest tables
python ingestion/upload_to_s3.py --table orders --table order_items

# did it all actually arrive?
python ingestion/verify_s3.py
```

## Configuration

Read from the environment (or the project-root `.env`):

| Variable | Used for |
|---|---|
| `S3_BUCKET` | default target bucket |
| `AWS_PROFILE` | named profile; leave empty to use the default credential chain |
| `AWS_REGION` | bucket region |

Credentials come from boto3's normal chain — environment variables, `~/.aws/credentials`,
AWS SSO, or an instance role. Neither script ever takes a key as an argument, so no
secret ends up in your shell history.

## Why `upload_file` and not `put_object`

`data/raw/orders/orders.csv` is roughly 1.5 GB at default scale. A single PUT of
that size will time out or die halfway and leave you guessing. `upload_file()` uses
S3's managed multipart transfer with its own concurrency and retry logic, which is
the whole reason the upload of the big fact files completes unattended.

## `verify_s3.py` is not optional

After an upload, "did it all get there?" is the only question that matters. A
truncated multipart upload or a forgotten table folder produces a `COPY INTO` that
*succeeds* with quietly wrong row counts — exactly the failure that is expensive to
diagnose three transformations later.

`verify_s3.py` compares local and remote in both directions and exits non-zero on
any mismatch, so it works as a pipeline gate:

```
MISSING IN S3  orders/orders.csv  (local 1.5 GB)
EXTRA IN S3    users/users_old.csv  (remote 12.3 MB)
```

`--allow-extra` tolerates stale remote objects when you only care about the
current data being present.

## In Airflow

The `zomato_batch` DAG does **not** upload — it assumes the files are already in
S3 and starts at `COPY INTO`. That is the normal split: uploading is a
publishing step (sometimes done by whoever produced the extract), while Airflow
owns the warehouse load and everything after it.

If you want a fully self-contained DAG, add a `PythonOperator` at the front that
calls `upload_to_s3.main()`, install `boto3` in the image, and pass `AWS_*`
credentials through `docker-compose.yaml`.
