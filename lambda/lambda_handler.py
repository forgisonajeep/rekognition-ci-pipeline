# lambda_handler.py
import os, json, datetime, time
from decimal import Decimal
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

# ---------- helpers

def iso_now() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def to_plain(x):
    """Pretty-print helper for CloudWatch logs."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, list):
        return [to_plain(v) for v in x]
    if isinstance(x, dict):
        return {k: to_plain(v) for k, v in x.items()}
    return x

def build_labels(resp: dict) -> list[dict]:
    """
    Normalize Rekognition response into DynamoDB-friendly list of
    {Name: str, Confidence: Decimal('99.99')}
    """
    labels = []
    for lbl in resp.get("Labels", []) or []:
        name = lbl.get("Name")
        conf = lbl.get("Confidence")
        if name is None or conf is None:
            continue
        # Keep DynamoDB Decimal (NOT float) in the item, but round sensibly
        labels.append({
            "Name": str(name),
            "Confidence": Decimal(str(round(float(conf), 2)))
        })
    return labels

# ---------- handler

def handler(event, context):
    region = os.environ.get("REGION", "us-east-1")
    table_name = os.environ["DDB_TABLE"]  # required
    branch = os.environ.get("BRANCH_HINT", "Lambda")

    rek = boto3.client("rekognition", region_name=region)
    ddb = boto3.resource("dynamodb", region_name=region).Table(table_name)

    # Parse S3 event (first record)
    try:
        rec = event["Records"][0]
        bucket = rec["s3"]["bucket"]["name"]
        # key may be URL-encoded by S3 notifications
        key = unquote_plus(rec["s3"]["object"]["key"])
    except Exception as e:
        print(json.dumps({
            "error": "Bad S3 event shape",
            "details": str(e),
            "event_sample": event
        }, indent=2))
        # Return a 400-style payload but don't raise (keeps pipeline resilient)
        return {"ok": False, "error": "bad_event"}

    # Rekognition
    try:
        resp = rek.detect_labels(
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            MaxLabels=10,
            MinConfidence=70.0,
        )
    except ClientError as e:
        print(json.dumps({
            "error": "Rekognition.detect_labels failed",
            "details": str(e),
            "bucket": bucket,
            "key": key
        }, indent=2))
        return {"ok": False, "error": "rekognition_failed"}

    labels = build_labels(resp)

    item = {
        "filename": key,           # e.g. rekognition-input/prod/sneaker-prod-test2.jpeg
        "labels": labels,          # list of {Name, Confidence(Decimal)}
        "timestamp": iso_now(),    # ISO8601 Zulu
        "branch": branch,          # "Lambda" or env hint
    }
    
    item["ttl"] = int(time.time()) + 7 * 24 * 60 * 60
    ddb.put_item(Item=item)

    # Pretty CloudWatch logs (human-readable, floats for viewing only)
    print(json.dumps({
        "filename": item["filename"],
        "labels": [{"Name": l["Name"], "Confidence": float(l["Confidence"])} for l in labels],
        "timestamp": item["timestamp"],
        "branch": item["branch"]
    }, indent=2))

    # Persist to DynamoDB (Decimals preserved)
    try:
        ddb.put_item(Item=item)
    except ClientError as e:
        print(json.dumps({
            "error": "DynamoDB.put_item failed",
            "details": str(e),
            "table": table_name,
            "about_to_write": to_plain(item)
        }, indent=2))
        return {"ok": False, "error": "ddb_failed"}

    return {"ok": True, "filename": key, "count": len(labels)}