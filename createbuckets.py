import boto3
import json


def create_bucket(name, region, cors_config, policy):
    print("Creating bucket", name)

    s3_client = boto3.client("s3")

    config = {"LocationConstraint": region}

    # us-east-1 does not need the constraint (and in fact errors if passed)
    if config["LocationConstraint"].lower() == "us-east-1":
        s3_client.create_bucket(Bucket=name)
    else:
        s3_client.create_bucket(Bucket=name, CreateBucketConfiguration=config)

    if cors_config is not None:
        s3_client.put_bucket_cors(Bucket=name, CORSConfiguration=cors_config)

    if policy is not None:
        s3_client.put_bucket_policy(Bucket=name, Policy=json.dumps(policy))


def input_bool(text):
    result = None
    while result is None or (result.lower() != "y" and result.lower() != "n"):
        try:
            result = input("%s [y/n]: " % text)
        except EOFError as e:
            exit()
    return result.lower() == "y"


def input_string(text):
    try:
        return input("%s: " % text)
    except EOFError as e:
        exit()


def _get_policy(bucket_name):
    return {
        "Version": "2008-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "AWS": "*"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::%s/*" % bucket_name
        }]
    }


def _get_cors_config(allowed_methods):
    return {
        "CORSRules": [{
            "AllowedHeaders": ["*"],
            "AllowedOrigins": ["*"],
            "AllowedMethods": allowed_methods,
            "MaxAgeSeconds": 3000
        }]
    }


def main():
    region = input_string("Region?")

    get_cors_config = _get_cors_config(["GET"])
    get_put_cors_config = _get_cors_config(["PUT", "GET"])

    # Create user upload bucket
    if input_bool("Create user uploads bucket?"):
        bucket_name = input_string(
            "Name for the user uploads bucket?")

        create_bucket(bucket_name, region, get_put_cors_config,
                      _get_policy(bucket_name))

    # Create image processing results bucket
    if input_bool("Create image processing results bucket?"):
        bucket_name = input_string(
            "Name for the image processing results bucket?")
        create_bucket(bucket_name, region, get_cors_config,
                      _get_policy(bucket_name))

    # Create image processing models bucket
    if input_bool("Create image processing models bucket?"):
        bucket_name = input_string(
            "Name for the image processing models bucket?")
        create_bucket(bucket_name, region, None, None)

    print("Done")


if __name__ == "__main__":
    main()
