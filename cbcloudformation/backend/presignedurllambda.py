from collections import namedtuple
from pathlib import Path
import troposphere as ts
import troposphere.iam
import troposphere.awslambda
from .parameters import BackendParameters
from .constants import presigned_url_fn_name


BackendPresignedUrlLambda = namedtuple("BackendPresignedUrlLambda", [
    "presigned_url_lambda_execution_role",
    "presigned_url_lambda",
])


def create_presigned_url_lambda(template: ts.Template, params: BackendParameters) -> BackendPresignedUrlLambda:
    # Create lambda execution role with S3 upload rights
    presigned_url_lambda_execution_role = template.add_resource(
        ts.iam.Role(
            "RegisterUploadsExecutionRole",
            Path="/",
            Policies=[
                ts.iam.Policy(
                    PolicyName="root",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": ["logs:*"],
                            "Resource": "arn:aws:logs:*:*:*",
                            "Effect": "Allow"
                        }]
                    }
                ),
                ts.iam.Policy(
                    PolicyName="s3UserUpload",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": ["s3:PutObject"],
                            "Effect": "Allow",
                            "Resource": ts.Sub("arn:aws:s3:::${BucketName}/*", BucketName=params.user_uploads_bucket_name.ref()),
                        }]
                    }
                ),
            ],
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {
                        "Service": ["lambda.amazonaws.com"]
                    }
                }]
            },
        )
    )

    # Create lambda function with code loaded from a file
    def _create_lambda(file_name, fn_name, bucket):
        with open(file_name, "r") as code_file:
            code_lines = code_file.readlines()

        return template.add_resource(
            ts.awslambda.Function(
                fn_name,
                Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                Handler="index.handler",
                Environment=ts.awslambda.Environment(
                    Variables={
                        "BUCKET": bucket.ref()
                    }
                ),
                Role=presigned_url_lambda_execution_role.get_att("Arn"),
                Runtime="nodejs14.x",
                MemorySize=128,  # TODO: Make this param
                Timeout=3  # TODO: Make this param
            )
        )

    # User upload
    script_path = Path(__file__).resolve().parent / "lambdas" / "getuploadpresignedurl.js"
    presigned_url_lambda = _create_lambda(script_path, presigned_url_fn_name, params.user_uploads_bucket_name)

    return BackendPresignedUrlLambda(
        presigned_url_lambda_execution_role,
        presigned_url_lambda
    )