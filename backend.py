import troposphere as ts
import troposphere.ec2
import troposphere.awslambda
import troposphere.iam
import troposphere.apigateway
import troposphere.s3
import troposphere.ecs
import troposphere.cloudformation
import troposphere.autoscaling
import troposphere.elasticloadbalancing
import troposphere.policies
import troposphere.ecr
import awacs
import awacs.iam
import awacs.s3


class BackendTemplateFactory:
    presigned_url_fn_name = "GetImageUploadPresignedUrl"
    image_processing_container_name = "ImageProcessingContainer"
    ecr_repository_name = "image-processing-backend"

    def create_template(self) -> ts.Template:
        self.template = ts.Template("Cambrian image processing backend")

        self.ref_stack_id = ts.Ref("AWS::StackId")
        self.tags_stack_id = ts.Tags(Application=self.ref_stack_id)

        self._create_vpc()
        self._create_s3_buckets()
        self._create_presigned_url_lambda()
        self._create_api_gateway()
        self._create_cluster()

        return self.template

    def _res(self, resource):
        return self.template.add_resource(resource)

    def _map(self, name, mapping):
        return self.template.add_mapping(name, mapping)

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
        # Create lambda execution role with S3 upload rights
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

    def _create_cluster(self):
        # Create cluster
        self.image_processing_cluster = self._res(ts.ecs.Cluster(
            "ImageProcessingCluster",
            DependsOn=self.vpc.title
        ))

        self.image_processing_instance_id_mapping = self._map("ImageProcessingInstanceId", {
            # https://docs.aws.amazon.com/AmazonECS/latest/developerguide/launch_container_instance.html
            "us-east-1": {"AMI": "ami-00cf4737e238866a3"},
            "us-east-2": {"AMI": "ami-012ca23958772cf72"},
            "us-west-1": {"AMI": "ami-06d87f0156b1d4407"},
            "us-west-2": {"AMI": "ami-0a9f5be2a016dccad"},
        })

        self.image_processing_launch_config = self._res(ts.autoscaling.LaunchConfiguration(
            "ImageProcessingLaunchConfiguration",
            Metadata=ts.autoscaling.Metadata(
                troposphere.cloudformation.Init({
                    "config": ts.cloudformation.InitConfig(
                        commands={
                            "01_add_instance_to_cluster": {
                                "command": ts.Join("", [
                                    "#!/bin/bash\n",
                                    "echo ECS_CLUSTER=",
                                    self.image_processing_cluster.ref(),
                                    " >> /etc/ecs/ecs.config"
                                ])
                            }
                        },
                        files=ts.cloudformation.InitFiles({
                            "/etc/cfn/cfn-hup.conf": ts.cloudformation.InitFile(
                                content=ts.Sub("""
                                [main]
                                stack=${AWS::StackId}
                                region=${AWS::Region}
                                """),
                                mode="00400",
                                owner="root",
                                group="root"
                            ),
                            "/etc/cfn/hooks.d/cfn-auto-reloader.conf": ts.cloudformation.InitFile(
                                content=ts.Sub("""
                                [cfn-auto-reloader-hook]
                                triggers=post.update
                                path=Resources.ContainerInstances.Metadata.AWS::CloudFormation::Init
                                action=/opt/aws/bin/cfn-init -v --stack ${AWS::StackName}
                                                                --resource ContainerInstances
                                                                --region ${AWS::Region}
                                runas=root
                                """),
                            ),
                        })
                    )
                })
            ),
            ImageId=ts.FindInMap("ImageProcessingInstanceId", ts.Ref(ts.AWS_REGION), "AMI"), # TODO: Map name automatic
            InstanceType="t2.medium"
        ))

        self.image_processing_auto_scaling_group = self._res(ts.autoscaling.AutoScalingGroup(
            "ImageProcessingAutoScalingGroup",
            VPCZoneIdentifier=[self.pub_sub.ref()],
            LaunchConfigurationName=self.image_processing_launch_config.ref(),
            MinSize=1,
            MaxSize=1,  # TODO: Parameter for this?
            DesiredCapacity=1,  # TODO: Parameter for this?
            CreationPolicy=ts.policies.CreationPolicy(
                ResourceSignal=ts.policies.ResourceSignal(
                    Timeout="PT5M"
                )
            ),
            UpdatePolicy=ts.policies.UpdatePolicy(
                AutoScalingRollingUpdate=ts.policies.AutoScalingRollingUpdate(
                    MinInstancesInService=1,
                    MaxBatchSize=1,
                    PauseTime="PT5M",
                    WaitOnResourceSignals=True
                )
            )
        ))

        # Create service and instance roles
        self.image_processing_service_role = self._res(ts.iam.Role(
            "ImageProcessingServiceRole",
            Path="/",
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {
                        "Service": ["ecs.amazonaws.com"]
                    }
                }]
            },
            Policies=[ts.iam.Policy(
                PolicyName="ImageProcessingServicePolicy",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Action": [
                            "ec2:AuthorizeSecurityGroupIngress",
                            "ec2:Describe*",
                            "elasticloadbalancing:DeregisterInstancesFromLoadBalancer",
                            "elasticloadbalancing:DeregisterTargets",
                            "elasticloadbalancing:Describe*",
                            "elasticloadbalancing:RegisterInstancesWithLoadBalancer",
                            "elasticloadbalancing:RegisterTargets"
                        ],
                        "Effect": "Allow",
                        "Resource": "*"
                    }]
                }
            )]
        ))

        self.image_processing_instance_role = self._res(ts.iam.Role(
            "ImageProcessingInstanceRole",
            Path="/",
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": ["sts:AssumeRole"],
                    "Effect": "Allow",
                    "Principal": {
                        "Service": ["ec2.amazonaws.com"]
                    }
                }]
            },
            Policies=[ts.iam.Policy(
                PolicyName="ImageProcessingInstancePolicy",
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Action": [
                            "ecs:CreateCluster",
                            "ecs:RegisterContainerInstance",
                            "ecs:DeregisterContainerInstance",
                            "ecs:DiscoverPollEndpoint",
                            "ecs:Submit*",
                            "ecr:*",
                            "ecs:Poll"
                        ],
                        "Effect": "Allow",
                        "Resource": "*"
                    }]
                }
            )]
        ))

        """
        # Create ECR
        self.image_processing_ecr_repo = self._res(ts.ecr.Repository(
            "ImageProcessingECRRepository",
            RepositoryName=self.ecr_repository_name,
            RepositoryPolicyText={
                "Version": "2008-10-17",
                "Statement": [{
                    "Action": [
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:PutImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload"
                    ],
                    "Effect": "Allow",
                    "Principal": {
                        "AWS": ts.Sub("arn:aws:iam::${AWS::AccountId}:root")
                    }
                }]
            }
        ))
        """

        self.image_processing_instance_profile = self._res(ts.iam.InstanceProfile(
            "ImageProcessingInstanceProfile",
            Path="/",
            Roles=[self.image_processing_instance_role.ref()]
        ))

        # Create load balancer
        self.image_processing_load_balancer_sg = self._res(ts.ec2.SecurityGroup(
            "ImageProcessingLoadBalancerSG",
            GroupDescription="Allow TCP traffic on 8080",
            VpcId=self.vpc.ref(),
            SecurityGroupIngress=[ts.ec2.SecurityGroupRule(
                "ImageProcessingLoadBalancerSGIngress",
                CidrIp="0.0.0.0/0",
                IpProtocol="tcp",
                FromPort=8080,
                ToPort=8080
            )]
        ))

        self.image_processing_load_balancer = self._res(ts.elasticloadbalancing.LoadBalancer(
            "ImageProcessingLoadBalancer",
            DependsOn=[self.image_processing_load_balancer_sg.title],
            Subnets=[self.pub_sub.ref()],
            Listeners=[ts.elasticloadbalancing.Listener(
                LoadBalancerPort=8080,
                InstancePort=8080,
                Protocol="HTTP"
            )],
            SecurityGroups=[self.image_processing_load_balancer_sg.ref()],
            HealthCheck=ts.elasticloadbalancing.HealthCheck(
                # Make an invalid segment request, TODO: Do it properly?
                Target="HTTP:8080/segment/invalidurl",
                HealthyThreshold="2",
                UnhealthyThreshold="10",
                Interval="30",
                Timeout=5
            ),
            Tags=self.tags_stack_id
        ))

        self.image_processing_task_def = self._res(ts.ecs.TaskDefinition(
            "ImageProcessingTaskDefinition",
            ContainerDefinitions=[ts.ecs.ContainerDefinition(
                Name=self.image_processing_container_name,
                Cpu=2048,
                Memory=4096,
                Essential=True,
                PortMappings=[ts.ecs.PortMapping(
                    HostPort=8080,
                    ContainerPort=8080
                )],
                Image=ts.Sub("${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ECRRepoName}", ECRRepoName=self.ecr_repository_name)
            )]
        ))

        # Create ECS service on cluster
        self.image_processing_service = self._res(ts.ecs.Service(
            "ImageProcessingService",
            DependsOn=self.image_processing_auto_scaling_group.title,
            Cluster=self.image_processing_cluster.ref(),
            DesiredCount=1,
            DeploymentConfiguration=ts.ecs.DeploymentConfiguration(
                MaximumPercent=100,
                MinimumHealthyPercent=0  # 0% Needed for dev updates
            ),
            LoadBalancers=[ts.ecs.LoadBalancer(
                ContainerName=self.image_processing_container_name,
                ContainerPort=8080,
                LoadBalancerName=self.image_processing_load_balancer.ref()
            )],
            Role=self.image_processing_service_role.ref(),
            TaskDefinition=self.image_processing_task_def.ref()
        ))


def main():
    template_factory = BackendTemplateFactory()

    template = template_factory.create_template()

    template_yaml = template.to_yaml()

    print(template_yaml)

    with open("backend.yml", "w") as output_file:
        output_file.write(template_yaml)


if __name__ == "__main__":
    main()
