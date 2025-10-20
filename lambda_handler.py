import os, json, datetime
from decimal import Decimal
import boto3

def iso_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def handler(event, context):
    region = os.environ["AWS_REGION"]
    table  = os.environ["DDB_TABLE"]

    rek = boto3.client("rekognition", region_name=region)
    ddb = boto3.resource("dynamodb", region_name=region).Table(table)

    rec    = event["Records"][0]
    bucket = rec["s3"]["bucket"]["name"]
    key    = rec["s3"]["object"]["key"]     # e.g. rekognition-input/beta/sneaker2.jpeg

    # Rekognition
    resp = rek.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=10, MinConfidence=70.0
    )
    labels = [
        {"Name": l["Name"], "Confidence": Decimal(str(round(l["Confidence"], 2)))}
        for l in resp.get("Labels", [])
    ]

    item = {
        "filename": key,
        "labels": labels,
        "timestamp": iso_now(),
        "branch": os.environ.get("BRANCH_HINT", "lambda"),
    }

    # Pretty log for CloudWatch (floats for readability)
    def to_plain(x):
        if isinstance(x, Decimal): return float(x)
        if isinstance(x, list):    return [to_plain(v) for v in x]
        if isinstance(x, dict):    return {k: to_plain(v) for k,v in x.items()}
        return x
    print(json.dumps(to_plain(item), indent=2))

    # Persist (Decimals required by DynamoDB)
    ddb.put_item(Item=item)
    return {"ok": True, "filename": item["filename"], "count": len(labels)}