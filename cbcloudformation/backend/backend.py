import troposphere as ts
from .parameters import create_parameters
from .network import create_network
from .sqs import create_sqs
from .presignedurllambda import create_presigned_url_lambda
from .projectexistslambda import create_project_exists_lambda
from .apigateway import create_api_gateway
from .cluster import create_cluster
from .backloglambda import create_backlog_lambda
from .scaling import create_scaling


def create_backend(template: ts.Template):
    params = create_parameters(template)

    network = create_network(template)
    sqs = create_sqs(template)
    presigned_url_lambda = create_presigned_url_lambda(template, params)
    project_exists_lambda = create_project_exists_lambda(template, params)
    api_gateway = create_api_gateway(template, presigned_url_lambda, project_exists_lambda, sqs)
    cluster = create_cluster(template, params, network, sqs)
    backlog_lambda = create_backlog_lambda(template, sqs, cluster)
    scaling = create_scaling(template, params, cluster)
