import troposphere as ts
import troposphere.ec2
import troposphere.awslambda
import troposphere.iam
import troposphere.apigateway
import troposphere.s3
import awacs
import awacs.iam
import awacs.s3


class BackendTemplateFactory:
    presigned_url_fn_name = "GetImageUploadPresignedUrl"

    def create_template(self) -> ts.Template:
        self.template = ts.Template("Cambrian image processing backend")

        self.ref_stack_id = ts.Ref("AWS::StackId")
        self.tags_stack_id = ts.Tags(Application=self.ref_stack_id)

        self._create_vpc()
        self._create_s3_buckets()
        self._create_presigned_url_lambda()
        self._create_api_gateway()

        return self.template

    def _res(self, resource):
        return self.template.add_resource(resource)

    def _create_vpc(self):
        # Create VPC
        self.vpc = self._res(
            ts.ec2.VPC("VPC", CidrBlock="10.0.0.0/16", Tags=self.tags_stack_id)
        )

        # Create subnets
        self.pub_sub = self._res(
            ts.ec2.Subnet("PublicSubnet", CidrBlock="10.0.0.0/24",
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id)
        )

        self.priv_sub = self._res(
            ts.ec2.Subnet("PrivateSubnet", CidrBlock="10.0.1.0/24",
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id)
        )

        # Create and attach internet gateway to public subnet
        self.internet_gateway = self._res(
            ts.ec2.InternetGateway("InternetGateway", Tags=self.tags_stack_id)
        )

        self.internet_gateway_attachment = self._res(
            ts.ec2.VPCGatewayAttachment(
                "AttachInternetGatewayToPublicSubdomain",
                VpcId=self.vpc.ref(),
                InternetGatewayId=self.internet_gateway.ref()
            )
        )

        # Create route table and routes to internet
        self.pub_route_table = self._res(
            ts.ec2.RouteTable(
                "RouteTable",
                VpcId=self.vpc.ref(),
                Tags=self.tags_stack_id
            )
        )

        self.pub_internet_route = self._res(
            ts.ec2.Route(
                "PublicInternetRoute",
                DependsOn=self.internet_gateway_attachment.title,
                GatewayId=self.internet_gateway.ref(),
                DestinationCidrBlock="0.0.0.0/0",
                RouteTableId=self.pub_route_table.ref()
            )
        )

        self.pub_subnet_route_table_association = self._res(
            ts.ec2.SubnetRouteTableAssociation(
                "PublicSubnetRouteTableAssociation",
                SubnetId=self.pub_sub.ref(),
                RouteTableId=self.pub_route_table.ref()
            )
        )

        # Create access control list
        self.network_acl = self._res(
            ts.ec2.NetworkAcl(
                "NetworkAcl",
                VpcId=self.vpc.ref(),
                Tags=self.tags_stack_id
            )
        )

        # TODO: ACL Rules

    def _create_s3_buckets(self):
        self.user_image_upload_bucket = self._res(
            ts.s3.Bucket(
                "CambrianUserImageUploads",
                AccessControl=ts.s3.Private
            )
        )

        self.image_processing_results_bucket = self._res(
            ts.s3.Bucket(
                "CambrianImageProcessingResults",
                AccessControl=ts.s3.PublicRead
            )
        )

        # Bucket that stores machine learning models etc.
        # that are downloaded on startup of an instance.
        self.image_processing_files_bucket = self._res(
            ts.s3.Bucket(
                "CambrianImageProcessingFiles",
                AccessControl=ts.s3.Private
            )
        )

    def _create_presigned_url_lambda(self):
        # Create lambda execution role
        self.presigned_url_lambda_execution_role = self._res(
            ts.iam.Role(
                "GetImageUploadPresignedUrlExecutionRole",
                DependsOn=self.user_image_upload_bucket.title,
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
                                "Resource": self.user_image_upload_bucket.get_att("Arn")
                            }]
                        }
                    )
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
        with open("getimageuploadpresignedurl.js", "r") as code_file:
            code_lines = code_file.readlines()

        self.presigned_url_lambda = self._res(
            ts.awslambda.Function(
                self.presigned_url_fn_name,
                DependsOn=self.user_image_upload_bucket.title,
                Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                Handler="index.handler",
                Environment=ts.awslambda.Environment(
                    Variables={
                        "BUCKET": self.user_image_upload_bucket.get_att("Arn")
                    }
                ),
                Role=self.presigned_url_lambda_execution_role.get_att("Arn"),
                Runtime="nodejs8.10",
                MemorySize=128,  # TODO: Make this param
                Timeout=3  # TODO: Make this param
            )
        )

    def _create_api_gateway(self):
        # Create REST api
        self.rest_api = self._res(
            ts.apigateway.RestApi(
                "RestApi",
                Name="RestApi"
            )
        )

        self.api_get_presigned = self._res(
            ts.apigateway.Resource(
                "GetImageUploadPresignedUrlRestApiResource",
                ParentId=self.rest_api.get_att("RootResourceId"),
                RestApiId=self.rest_api.ref(),
                PathPart='GetImageUploadPresignedUrl'
            )
        )

        # Create lambda permissions for api gateway
        self.rest_api_get_presigned_permissions = self._res(
            ts.awslambda.Permission(
                "RestApiGetPresignedUrlPermissions",
                Action="lambda:invokeFunction",
                Principal="apigateway.amazonaws.com",
                FunctionName=self.presigned_url_lambda.get_att("Arn"),
                SourceArn=ts.Sub("arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${apiName}/*/*/${funcName}",
                                 apiName=self.rest_api.ref(), funcName=self.presigned_url_fn_name)
            )
        )

        self.api_get_presigned_method = self._res(
            ts.apigateway.Method(
                "GetImageUploadPresignedUrlRestApiMethod",
                DependsOn=self.presigned_url_lambda.title,
                HttpMethod="GET",
                ResourceId=self.api_get_presigned.ref(),
                RestApiId=self.rest_api.ref(),
                AuthorizationType="NONE",
                Integration=ts.apigateway.Integration(
                    Type="AWS_PROXY",
                    IntegrationHttpMethod="POST",
                    IntegrationResponses=[
                        ts.apigateway.IntegrationResponse(StatusCode="200")
                    ],
                    Uri=ts.Sub("arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${lambdaArn}/invocations",
                               lambdaArn=self.presigned_url_lambda.get_att("Arn"))
                ),
                MethodResponses=[
                    ts.apigateway.MethodResponse(
                        "GetImageUploadPresignedUrlRestApiResponse",
                        StatusCode="200"
                    )
                ]
            )
        )

        self.api_deployment = self._res(
            ts.apigateway.Deployment(
                "RestApiDeployment",
                DependsOn=self.api_get_presigned_method.title,
                RestApiId=self.rest_api.ref()
            )
        )

        self.api_stage = self._res(
            ts.apigateway.Stage(
                "RestApiStage",
                StageName="v1",
                RestApiId=self.rest_api.ref(),
                DeploymentId=self.api_deployment.ref()
            )
        )


def main():
    template_factory = BackendTemplateFactory()

    template = template_factory.create_template()

    template_yaml = template.to_yaml()

    print(template_yaml)

    with open("backend.yml", "w") as output_file:
        output_file.write(template_yaml)


if __name__ == "__main__":
    main()
