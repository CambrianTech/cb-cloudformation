from collections import namedtuple
import troposphere as ts


BackendParameters = namedtuple("BackendParameters", [
    "ecr_repository_name",
    "ecr_planes_repository_name",
    "image_processing_files_bucket_name",
    "user_uploads_bucket_name",
    "image_processing_results_bucket_name",
    "min_instances",
    "max_instances",
])


def create_parameters(template: ts.Template) -> BackendParameters:
    ecr_repository_name = template.add_parameter(ts.Parameter(
        "ImageProcessingServiceRepository",
        Type="String",
        Default="312943975091.dkr.ecr.us-east-1.amazonaws.com/cb-imageprocessingservice-api-3-dev-sqs:latest",
        Description="ECR Repository for the docker image to use."
    ))

    ecr_planes_repository_name = template.add_parameter(ts.Parameter(
        "PlanesServiceRepository",
        Type="String",
        Default="312943975091.dkr.ecr.us-east-1.amazonaws.com/cb-planes:latest",
        Description="ECR Repository for the planes docker image to use."
    ))

    image_processing_files_bucket_name = template.add_parameter(ts.Parameter(
        "ImageProcessingFilesBucket",
        Type="String",
        Default="cb-imageprocessingservice-models",
        Description="S3 bucket with the files (models etc.) that the container will download on startup."
    ))

    user_uploads_bucket_name = template.add_parameter(ts.Parameter(
        "ImageProcessingUserUploadsBucket",
        Type="String",
        Default="cb-backend-data",
        Description="S3 bucket where user uploaded content will be stored."
    ))

    image_processing_results_bucket_name = template.add_parameter(ts.Parameter(
        "ImageProcessingResultsBucket",
        Type="String",
        Default="cb-backend-data",
        Description="S3 bucket where processed images will be stored."
    ))

    min_instances = template.add_parameter(ts.Parameter(
        "MinimumInstances",
        Type="Number",
        Default=2,
        Description="Minimum number of instances and tasks for the cluster."
    ))

    max_instances = template.add_parameter(ts.Parameter(
        "MaximumInstances",
        Type="Number",
        Default=4,
        Description="Maximum number of instances and tasks for the cluster."
    ))

    return BackendParameters(
        ecr_repository_name,
        ecr_planes_repository_name,
        image_processing_files_bucket_name,
        user_uploads_bucket_name,
        image_processing_results_bucket_name,
        min_instances,
        max_instances,
    )