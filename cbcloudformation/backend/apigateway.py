from collections import namedtuple
import troposphere as ts
import troposphere.apigateway
import troposphere.iam
import troposphere.awslambda
from .constants import register_uploads_fn_name, project_exists_fn_name
from .registeruploadslambda import BackendRegisterUploadsLambda
from .projectexistslambda import BackendProjectExistsLambda
from .sqs import BackendSqs

BackendApiGateway = namedtuple("BackendApiGateway", [
    "rest_api",

    "register_uploads_permission",
    "register_uploads_resource",
    "register_uploads_method",

    "project_exists_permission", 
    "project_exists_resource", 
    "project_exists_method",

    "api_image_processing",
    "api_image_processing_segment_resource",
    "api_image_processing_segment_key_resource",
    "api_image_processing_segment_role",
    "api_image_processing_method",
    "api_deployment",
    "api_stage",
])


def create_api_gateway(
    template: ts.Template,
    register_uploads_lambda: BackendRegisterUploadsLambda,
    project_exists_lambda: BackendProjectExistsLambda,
    sqs: BackendSqs,
    ) -> BackendApiGateway:

    # Create REST api
    rest_api = template.add_resource(
        ts.apigateway.RestApi("cbv4", Name="cbv4")
    )

    def _add_lambda(l, fn_name, resource=rest_api):
        # Create lambda permissions for api gateway
        permissions = template.add_resource(
            ts.awslambda.Permission(
                fn_name + "LambdaPermissions",
                Action="lambda:invokeFunction",
                Principal="apigateway.amazonaws.com",
                FunctionName=l.get_att("Arn"),
                SourceArn=ts.Sub("arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${apiName}/*/*/${funcName}",
                apiName=resource.ref(), funcName=fn_name)
            )
        )

        api = template.add_resource(
            ts.apigateway.Resource(
                fn_name + "Resource",
                ParentId=resource.get_att("RootResourceId"),
                RestApiId=resource.ref(),
                PathPart=fn_name
            )
        )

        method = template.add_resource(
            ts.apigateway.Method(
                fn_name + "Method",
                DependsOn=l.title,
                HttpMethod="GET",
                ResourceId=api.ref(),
                RestApiId=resource.ref(),
                AuthorizationType="NONE",
                Integration=ts.apigateway.Integration(
                    Type="AWS_PROXY",
                    IntegrationHttpMethod="POST",
                    IntegrationResponses=[
                        ts.apigateway.IntegrationResponse(StatusCode="200")
                    ],
                    Uri=ts.Sub("arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${lambdaArn}/invocations",
                    lambdaArn=l.get_att("Arn"))
                ),
                MethodResponses=[
                    ts.apigateway.MethodResponse(
                        fn_name + "Response",
                        StatusCode="200"
                    )
                ]
            )
        )

        return permissions, api, method

    register_uploads_permission, register_uploads_resource, register_uploads_method = _add_lambda(register_uploads_lambda.register_uploads_lambda, register_uploads_fn_name)

    project_exists_permission, project_exists_resource, project_exists_method = _add_lambda(project_exists_lambda.project_exists_lambda, project_exists_fn_name)


    # Wire up load balancer with api gateway (url/ImageProcessing/*)
    api_image_processing = template.add_resource(
        ts.apigateway.Resource(
            "ImageProcessingRestApiResource",
            ParentId=rest_api.get_att("RootResourceId"),
            RestApiId=rest_api.ref(),
            PathPart="ImageProcessing"
        )
    )

    api_image_processing_segment_resource = template.add_resource(
        ts.apigateway.Resource(
            "ImageProcessingSegmentResource",
            ParentId=api_image_processing.ref(),
            RestApiId=rest_api.ref(),
            PathPart="planes"
        )
    )

    api_image_processing_segment_key_resource = template.add_resource(
        ts.apigateway.Resource(
            "ImageProcessingSegmentKeyResource",
            ParentId=api_image_processing_segment_resource.ref(),
            RestApiId=rest_api.ref(),
            PathPart="{key}"
        )
    )

    api_image_processing_segment_role = template.add_resource(
        ts.iam.Role(
            "ImageProcessingProcessRole",
            DependsOn=[sqs.image_processing_queue.title],
            Path="/",
            Policies=[
                ts.iam.Policy(
                    PolicyName="SqsSendMessage",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": [
                                "sqs:SendMessage",
                            ],
                            "Effect": "Allow",
                            "Resource": [
                                sqs.image_processing_queue.get_att("Arn"),
                            ]
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
                        "Service": ["apigateway.amazonaws.com"]
                    }
                }]
            },
        )
    )

    api_image_processing_method = template.add_resource(
        ts.apigateway.Method(
            "ImageProcessingMethod",
            DependsOn=[
                api_image_processing_segment_role.title,
                sqs.image_processing_queue.title,
                api_image_processing_segment_key_resource.title,
            ],
            HttpMethod="GET",
            ResourceId=api_image_processing_segment_key_resource.ref(),
            RestApiId=rest_api.ref(),
            AuthorizationType="NONE",
            RequestParameters={
                "method.request.querystring.MessageBody": False,
            },
            Integration=ts.apigateway.Integration(
                Type="AWS",
                Credentials=api_image_processing_segment_role.get_att("Arn"),
                IntegrationHttpMethod="POST",
                IntegrationResponses=[
                    ts.apigateway.IntegrationResponse(
                        "ImageProcessingIntegrationResponse",
                        StatusCode="200",
                        ResponseParameters={"method.response.header.Access-Control-Allow-Origin": "'*'"},
                        ResponseTemplates={
                            "application/json": "\n".join([
                                "#set($key = $util.escapeJavaScript($input.params('key')))",
                                "#set($inputRoot = $input.path('$'))",
                                "{",
                                "    \"data_url\": \"$key/data.json\"",
                                "}",
                            ])
                        }
                    )
                ],
                Uri=ts.Sub("arn:aws:apigateway:${AWS::Region}:sqs:action/SendMessage"),
                RequestParameters={
                    "integration.request.querystring.QueueUrl": ts.Join("", ["'", sqs.image_processing_queue.ref(), "'"]),
                    "integration.request.querystring.MessageGroupId": "'default'",
                },
                RequestTemplates={
                    "application/json": "\n".join([
                        "#set($key = $util.escapeJavaScript($input.params('key')))",
                        "#set($context.requestOverride.querystring.MessageBody = \"{\"\"unique_id\"\": \"\"$key\"\"}\")",
                    ])
                },
                PassthroughBehavior="NEVER",
            ),
            MethodResponses=[
                ts.apigateway.MethodResponse(
                    "ImageProcessingResponse",
                    StatusCode="200",
                    ResponseParameters={"method.response.header.Access-Control-Allow-Origin": "'*'"},
                    ResponseModels={"application/json": "Empty"}
                )
            ]
        ),
    )

    api_deployment = template.add_resource(
        ts.apigateway.Deployment(
            "RestApiDeployment",
            DependsOn=[register_uploads_method.title, project_exists_method.title, api_image_processing_method.title],
            RestApiId=rest_api.ref()
        )
    )

    api_stage = template.add_resource(
        ts.apigateway.Stage(
            "RestApiStage",
            StageName="v1",
            RestApiId=rest_api.ref(),
            DeploymentId=api_deployment.ref()
        )
    )

    return BackendApiGateway(
        rest_api,

        register_uploads_permission,
        register_uploads_resource,
        register_uploads_method,

        project_exists_permission, 
        project_exists_resource, 
        project_exists_method,

        api_image_processing,
        api_image_processing_segment_resource,
        api_image_processing_segment_key_resource,
        api_image_processing_segment_role,
        api_image_processing_method,

        api_deployment,
        api_stage,
    )