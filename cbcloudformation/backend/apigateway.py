from collections import namedtuple
import troposphere as ts
import troposphere.apigateway
import troposphere.iam
import troposphere.awslambda
from .constants import presigned_url_fn_name
from .presignedurllambda import BackendPresignedUrlLambda
from .sqs import BackendSqs

#follow for all the scripted stuff in the api-gateway like in "#set($key = $util.escapeJavaScript($input.params('key')))",
#https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-mapping-template-reference.html

BackendApiGateway = namedtuple("BackendApiGateway", [
    "rest_api",
    "rest_api_get_presigned_permissions",
    "api_get_presigned",
    "api_get_presigned_method",
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
    presigned_url_lambda: BackendPresignedUrlLambda,
    sqs: BackendSqs,
    name="cbar",
    ) -> BackendApiGateway:
    
    # Create REST api
    rest_api = template.add_resource(
        ts.apigateway.RestApi(
            name,
            Name=name
        )
    )

    def _add_lambda(l, name, fn_name):
        # Create lambda permissions for api gateway
        permissions = template.add_resource(
            ts.awslambda.Permission(
                "RestApiGet" + name + "PresignedUrlPermissions",
                Action="lambda:invokeFunction",
                Principal="apigateway.amazonaws.com",
                FunctionName=l.get_att("Arn"),
                SourceArn=ts.Sub("arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${apiName}/*/*/${funcName}",
                                apiName=rest_api.ref(), funcName=fn_name)
            )
        )

        api = template.add_resource(
            ts.apigateway.Resource(
                "Get" + name + "PresignedUrlRestApiResource",
                ParentId=rest_api.get_att("RootResourceId"),
                RestApiId=rest_api.ref(),
                PathPart='Get' + name + 'PresignedUrl'
            )
        )

        method = template.add_resource(
            ts.apigateway.Method(
                "Get" + name + "PresignedUrlRestApiMethod",
                DependsOn=l.title,
                HttpMethod="GET",
                ResourceId=api.ref(),
                RestApiId=rest_api.ref(),
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
                        "Get" + name + "PresignedUrlRestApiResponse",
                        StatusCode="200"
                    )
                ]
            )
        )

        return permissions, api, method

    rest_api_get_presigned_permissions, api_get_presigned, api_get_presigned_method = _add_lambda(presigned_url_lambda.presigned_url_lambda, "UserUpload", presigned_url_fn_name)

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
                        ResponseTemplates={
                            "application/json": "\n".join([
                                "#set($key = $util.escapeJavaScript($input.params('key')))",
                                "#set($inputRoot = $input.path('$'))",
                                "{",
                                "    \"lighting_url\": \"$key/lighting.png\",",
                                "    \"semantic_url\": \"$key/mask.png\",",
                                "    \"data_url\": \"$key/data_v3.json\",",
                                "    \"data_v3_url\": \"$key/data_v3.json\"",
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
                        "#set($context.requestOverride.querystring.MessageBody = \"{\"\"image_s3_key\"\": \"\"$key\"\"}\")",
                    ])
                },
                PassthroughBehavior="NEVER",
            ),
            MethodResponses=[
                ts.apigateway.MethodResponse(
                    "ImageProcessingResponse",
                    StatusCode="200"
                )
            ]
        ),
    )

    api_deployment = template.add_resource(
        ts.apigateway.Deployment(
            "RestApiDeployment",
            DependsOn=[api_get_presigned_method.title,
                        api_image_processing_method.title],
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
        rest_api_get_presigned_permissions,
        api_get_presigned,
        api_get_presigned_method,
        api_image_processing,
        api_image_processing_segment_resource,
        api_image_processing_segment_key_resource,
        api_image_processing_segment_role,
        api_image_processing_method,
        api_deployment,
        api_stage,
    )