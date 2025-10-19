import os, json, datetime, pathlib
import boto3

def iso_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def main():
    aws_region = os.environ["AWS_REGION"]
    s3_bucket  = os.environ["S3_BUCKET"]
    ddb_table  = os.environ["DYNAMODB_TABLE"]
    branch     = os.environ.get("GITHUB_REF_NAME", "unknown")

    s3  = boto3.client("s3", region_name=aws_region)
    rek = boto3.client("rekognition", region_name=aws_region)
    ddb = boto3.resource("dynamodb", region_name=aws_region).Table(ddb_table)

    images_dir = pathlib.Path("images")
    files = [p for p in images_dir.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if not files:
        print("No images found under images/. Nothing to do.")
        return

    for path in files:
        key = f"rekognition-input/{path.name}"
        print(f"Uploading {path} to s3://{s3_bucket}/{key}")
        s3.upload_file(str(path), s3_bucket, key)

        print(f"Detecting labels for s3://{s3_bucket}/{key}")
        resp = rek.detect_labels(
            Image={"S3Object": {"Bucket": s3_bucket, "Name": key}},
            MaxLabels=10,
            MinConfidence=70.0
        )
        from decimal import Decimal

        labels = [
            {"Name": l["Name"], "Confidence": Decimal(str(round(l["Confidence"], 2)))}
            for l in resp.get("Labels", [])
        ]

        item = {
            "filename": f"rekognition-input/{path.name}",
            "labels": labels,
            "timestamp": iso_now(),
            "branch": branch,
        }
        print("Writing result to DynamoDB:", json.dumps(item, indent=2))
        ddb.put_item(Item=item)

if __name__ == "__main__":
    main()