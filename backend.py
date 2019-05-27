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
import troposphere.helpers
import troposphere.helpers.userdata
import troposphere.logs
import troposphere.cloudwatch
import troposphere.applicationautoscaling


class BackendTemplateFactory:
    presigned_url_fn_name = "GetImageUploadPresignedUrl"
    image_processing_container_name = "ImageProcessingContainer"

    ecr_repository_name = "cb-imageprocessingservice-gpu:latest"
    image_processing_files_bucket_name = "cb-imageprocessingservice"
    user_image_uploads_bucket_name = "cb-user-image-uploads"
    image_processing_results_bucket_name = "cb-imageprocessingservice-results"

    scale_up_threshold = 10
    scale_down_threshold = 3

    def create_template(self) -> ts.Template:
        self.template = ts.Template("Cambrian image processing backend")

        self.ref_stack_id = ts.Ref("AWS::StackId")
        self.tags_stack_id = ts.Tags(Application=self.ref_stack_id)

        self._create_vpc()
        self._create_s3_buckets()
        self._create_presigned_url_lambda()
        self._create_api_gateway()
        self._create_cluster()
        self._create_api_stage()
        self._create_scaling()

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
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id,
                          AvailabilityZone=ts.Sub("${AWS::Region}a"))
        )

        self.pub_sub2 = self._res(
            ts.ec2.Subnet("PublicSubnet2", CidrBlock="10.0.1.0/24",
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id,
                          AvailabilityZone=ts.Sub("${AWS::Region}b"))
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

        self.pub_subnet2_route_table_association = self._res(
            ts.ec2.SubnetRouteTableAssociation(
                "PublicSubnet2RouteTableAssociation",
                SubnetId=self.pub_sub2.ref(),
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
        pass
        """
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
        )"""

    def _create_presigned_url_lambda(self):
        # Create lambda execution role with S3 upload rights
        self.presigned_url_lambda_execution_role = self._res(
            ts.iam.Role(
                "GetImageUploadPresignedUrlExecutionRole",
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
                                "Resource": "arn:aws:s3:::%s/*" % self.image_processing_results_bucket_name,
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
                Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                Handler="index.handler",
                Environment=ts.awslambda.Environment(
                    Variables={
                        "BUCKET": self.user_image_uploads_bucket_name
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

    def _create_cluster(self):
        # Create cluster
        self.image_processing_cluster = self._res(ts.ecs.Cluster(
            "ImageProcessingCluster",
            DependsOn=self.vpc.title
        ))

        self.image_processing_instance_id_mapping = self._map("ImageProcessingInstanceId", {
            # https://docs.aws.amazon.com/AmazonECS/latest/developerguide/launch_container_instance.html
            # base: ami-0b0ae551a867891da
            "us-east-1": {"AMI": "ami-0e42ab1386f42d461"},
            # TODO: Build more custom AMIs and add them here
        })

        self.image_processing_instance_sg = self._res(ts.ec2.SecurityGroup(
            "ImageProcessingInstanceSG",
            GroupDescription="Allow TCP traffic on 8080",
            VpcId=self.vpc.ref(),
            SecurityGroupIngress=[
                ts.ec2.SecurityGroupRule(
                    "ImageProcessingLoadBalancerSGIngress",
                    CidrIp="0.0.0.0/0",
                    IpProtocol="tcp",
                    FromPort=8080,
                    ToPort=8080
                ),
            ]
        ))

        self.image_processing_launch_config = self._res(ts.autoscaling.LaunchConfiguration(
            "ImageProcessingLaunchConfiguration",
            Metadata=ts.autoscaling.Metadata(
                ts.cloudformation.Init({
                    "config": ts.cloudformation.InitConfig(
                        commands={
                            "01_add_instance_to_cluster": {
                                "command": ts.Join("", [
                                    "#!/bin/bash\n",
                                    "echo ECS_CLUSTER=",
                                    self.image_processing_cluster.ref(),
                                    " >> /etc/ecs/ecs.config\n",
                                    "echo ECS_ENABLE_CONTAINER_METADATA=1",
                                    " >> /etc/ecs/ecs.config"
                                ])
                            }
                        },
                        files=ts.cloudformation.InitFiles({
                            "/etc/cfn/cfn-hup.conf": ts.cloudformation.InitFile(
                                content=ts.Sub((
                                    "[main]\n"
                                    "stack=${AWS::StackId}\n"
                                    "region=${AWS::Region}\n"
                                )),
                                mode="00400",
                                owner="root",
                                group="root"
                            ),
                            "/etc/cfn/hooks.d/cfn-auto-reloader.conf": ts.cloudformation.InitFile(
                                content=ts.Sub((
                                    "[cfn-auto-reloader-hook]\n"
                                    "triggers=post.update\n"
                                    "path=Resources.ContainerInstances.Metadata.AWS::CloudFormation::Init\n"
                                    "action=/opt/aws/bin/cfn-init -v --stack ${AWS::StackName}"
                                    # TODO: Get resource name from title
                                    " --resource ImageProcessingLaunchConfiguration"
                                    " --region ${AWS::Region}\n"
                                    "runas=root\n"
                                )),
                            ),
                        }),
                        services={
                            "sysvinit": {
                                'cfn-hup': ts.cloudformation.InitService(
                                    ensureRunning='true',
                                    enabled='true',
                                    files=['/etc/cfn/cfn-hup.conf',
                                           '/etc/cfn/hooks.d/cfn-auto-reloader.conf']
                                ),
                                "docker": {"enabled": "true", "ensureRunning": "true"}
                            }
                        },
                        packages={
                            "yum": {
                                "docker": [],
                                "ecs-init": [],
                            }
                        }
                    )
                })
            ),
            ImageId=ts.FindInMap("ImageProcessingInstanceId", ts.Ref(
                ts.AWS_REGION), "AMI"),  # TODO: Map name automatic
            InstanceType="g3.4xlarge",
            UserData=ts.Base64(
                # https://github.com/DiUS/cloudformation-templates/blob/b0dbf24f62dfa7c6867908cda168598f318bd6e3/ECS/ecs-cluster.template#L341-L365
                ts.Join("", [
                    "#!/bin/bash -xe\n",
                    "yum -y update\n",
                    "yum install -y aws-cfn-bootstrap\n",
                    "/opt/aws/bin/cfn-init -v ",
                    " --stack ",
                    ts.Ref(ts.AWS_STACK_NAME),
                    # TODO: Get resource name from title
                    " --resource %s " % "ImageProcessingLaunchConfiguration",
                    " --region ",
                    ts.Ref(ts.AWS_REGION),
                    "\n",
                    "/opt/aws/bin/cfn-signal -e $? ",
                    " --stack ",
                    ts.Ref(ts.AWS_STACK_NAME),
                    # TODO: Get resource name from title
                    " --resource ImageProcessingAutoScalingGroup",
                    " --region ",
                    ts.Ref(ts.AWS_REGION),
                    "\n"
                ])
            ),
            IamInstanceProfile=ts.Ref(
                "ImageProcessingInstanceProfile"),  # TODO: Get from self
            SecurityGroups=[self.image_processing_instance_sg.ref()],
            # necessary for 1 minute metrics (5 minute is default)
            InstanceMonitoring=True,
            AssociatePublicIpAddress=True,
            # KeyName="imageprocessing-instance"
        ))

        self.image_processing_auto_scaling_group = self._res(ts.autoscaling.AutoScalingGroup(
            "ImageProcessingAutoScalingGroup",
            VPCZoneIdentifier=[self.pub_sub.ref(), self.pub_sub2.ref()],
            LaunchConfigurationName=self.image_processing_launch_config.ref(),
            MinSize=1,
            MaxSize=2,  # TODO: Parameter for this?
            DesiredCapacity=1,  # TODO: Parameter for this?

            # Wait 5 minutes before timing out when not receiving health signal
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
            Policies=[
                ts.iam.Policy(
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
                                "ecs:Poll",
                                "ecs:StartTelemetrySession",
                                "ecs:SubmitContainerStateChange",
                                "ecs:SubmitTaskStateChange",
                                "cloudwatch:PutMetricData",
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                                "logs:DescribeLogStreams",
                            ],
                            "Effect": "Allow",
                            "Resource": "*"
                        }]
                    }
                ),
                ts.iam.Policy(
                    PolicyName="ImageProcessingInstancePolicyS3Files",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": ["s3:GetObject", "s3:ListBucket"],
                            "Effect": "Allow",
                            "Resource": [
                                "arn:aws:s3:::%s" % self.image_processing_files_bucket_name,  # TODO
                                "arn:aws:s3:::%s/*" % self.image_processing_files_bucket_name,
                                "arn:aws:s3:::%s" % self.user_image_uploads_bucket_name,
                                "arn:aws:s3:::%s/*" % self.user_image_uploads_bucket_name,
                            ]
                        }]
                    }
                ),
                ts.iam.Policy(
                    PolicyName="ImageProcessingInstancePolicyS3UserUploads",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": ["s3:PutObject"],
                            "Effect": "Allow",
                            "Resource": [
                                "arn:aws:s3:::%s/*" % self.image_processing_results_bucket_name,
                            ]
                        }]
                    }
                ),
            ]
        ))

        self.image_processing_instance_profile = self._res(ts.iam.InstanceProfile(
            "ImageProcessingInstanceProfile",
            Path="/",
            Roles=[self.image_processing_instance_role.ref()]
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

        # Create load balancer
        self.image_processing_load_balancer_sg = self._res(ts.ec2.SecurityGroup(
            "ImageProcessingLoadBalancerSG",
            GroupDescription="Allow TCP traffic on 8080",
            VpcId=self.vpc.ref(),
            SecurityGroupIngress=[
                ts.ec2.SecurityGroupRule(
                    "ImageProcessingLoadBalancerSGIngress",
                    CidrIp="0.0.0.0/0",
                    IpProtocol="tcp",
                    FromPort=8080,
                    ToPort=8080
                ),
            ]
        ))

        self.image_processing_load_balancer = self._res(ts.elasticloadbalancing.LoadBalancer(
            "ImageProcessingLoadBalancer",
            DependsOn=[self.image_processing_load_balancer_sg.title],
            Subnets=[self.pub_sub.ref(), self.pub_sub2.ref()],
            Listeners=[ts.elasticloadbalancing.Listener(
                LoadBalancerPort=8080,
                InstancePort=8080,
                Protocol="HTTP"
            )],
            SecurityGroups=[self.image_processing_load_balancer_sg.ref()],
            HealthCheck=ts.elasticloadbalancing.HealthCheck(
                Target="HTTP:8080/healthcheck",
                HealthyThreshold="2",
                UnhealthyThreshold="10",
                Interval="45",
                Timeout=5
            ),
            Tags=self.tags_stack_id
        ))

        self.image_processing_log_group = self._res(ts.logs.LogGroup(
            "ImageProcessingLogGroup",
            LogGroupName=ts.Join("-", [
                "ImageProcessingLogGroup",
                ts.Ref(ts.AWS_STACK_NAME)
            ]),
            RetentionInDays=14
        ))

        self.image_processing_task_def = self._res(ts.ecs.TaskDefinition(
            "ImageProcessingTaskDefinition",
            ContainerDefinitions=[ts.ecs.ContainerDefinition(
                Name=self.image_processing_container_name,
                Essential=True,
                PortMappings=[ts.ecs.PortMapping(
                    HostPort=8080,
                    ContainerPort=8080
                )],
                MemoryReservation=4096,
                # Can't specify GPU requirements yet (see https://github.com/aws/containers-roadmap/issues/223).
                # Use a requirements of 16 CPUs meanwhile (as many as a g3.4xlarge has)
                Cpu=16*1024,
                Image=ts.Sub("${AWS::AccountId}.dkr.ecr.${AWS::Region}.amazonaws.com/${ECRRepoName}",
                             ECRRepoName=self.ecr_repository_name),
                LogConfiguration=ts.ecs.LogConfiguration(
                    LogDriver="awslogs",
                    Options={
                        "awslogs-group": self.image_processing_log_group.ref(),
                        "awslogs-region": ts.Ref(ts.AWS_REGION),
                        "awslogs-stream-prefix": "image-processing-service"
                    }
                )
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

        # Wire up load balancer with api gateway (url/ImageProcessing/*)
        self.api_image_processing = self._res(
            ts.apigateway.Resource(
                "ImageProcessingRestApiResource",
                ParentId=self.rest_api.get_att("RootResourceId"),
                RestApiId=self.rest_api.ref(),
                PathPart="ImageProcessing"
            )
        )

        self.api_image_processing_proxy = self._res(
            ts.apigateway.Resource(
                "ImageProcessingProxyRestApiResource",
                ParentId=self.api_image_processing.ref(),
                RestApiId=self.rest_api.ref(),
                PathPart="{proxy+}"
            )
        )

        self.api_image_processing_method = self._res(
            ts.apigateway.Method(
                "ImageProcessingMethod",
                DependsOn=self.image_processing_service.title,
                HttpMethod="ANY",
                ResourceId=self.api_image_processing_proxy.ref(),
                RestApiId=self.rest_api.ref(),
                AuthorizationType="NONE",
                RequestParameters={
                    "method.request.path.proxy": "true",
                },
                Integration=ts.apigateway.Integration(
                    Type="HTTP_PROXY",
                    IntegrationHttpMethod="ANY",
                    PassthroughBehavior="WHEN_NO_MATCH",
                    RequestParameters={
                        "integration.request.path.proxy": "method.request.path.proxy",
                    },
                    Uri=ts.Join("", [
                                "http://", self.image_processing_load_balancer.get_att("DNSName"), ":8080", "/{proxy}"])
                ),
                MethodResponses=[
                    ts.apigateway.MethodResponse(
                        "ImageProcessingResponse",
                        StatusCode="200"
                    )
                ]
            )
        )

    def _create_api_stage(self):
        self.api_deployment = self._res(
            ts.apigateway.Deployment(
                "RestApiDeployment",
                DependsOn=[self.api_get_presigned_method.title,
                           self.api_image_processing_method.title],
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

    def _create_scaling(self):
        # Create role and target needed for container scaling
        self.image_processing_container_scaling_role = self._res(ts.iam.Role(
            "ImageProcessingContainerScalingRole",
            Path="/",
            Policies=[
                ts.iam.Policy(
                    PolicyName="ImageProcessingContainerScalingRolePolicy",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": [
                                "ecs:UpdateService",
                                "ecs:DescribeServices",
                                "application-autoscaling:*",
                                "cloudwatch:DescribeAlarms",
                                "cloudwatch:GetMetricStatistics",
                            ],
                            "Effect": "Allow",
                            "Resource": "*",
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
                        "Service": ["application-autoscaling.amazonaws.com"]
                    }
                }]
            },
        ))

        self.image_processing_container_scaling_target = self._res(ts.applicationautoscaling.ScalableTarget(
            "ImageProcessingContainerScalingTarget",
            MinCapacity=1,
            MaxCapacity=2,
            ScalableDimension="ecs:service:DesiredCount",
            ServiceNamespace="ecs",
            ResourceId=ts.Join("/", [
                "service",
                self.image_processing_cluster.ref(),
                self.image_processing_service.get_att("Name")
            ]),
            RoleARN=self.image_processing_container_scaling_role.get_att("Arn")
        ))

        # Create container scaling policy
        self.image_processing_container_scale_up_policy = self._res(ts.applicationautoscaling.ScalingPolicy(
            "ImageProcessingContainerScaleUpPolicy",
            PolicyName="ImageProcessingContainerScaleUpPolicy",
            PolicyType="StepScaling",
            ScalingTargetId=self.image_processing_container_scaling_target.ref(),
            ScalableDimension="ecs:service:DesiredCount",
            ServiceNamespace="ecs",
            StepScalingPolicyConfiguration=ts.applicationautoscaling.StepScalingPolicyConfiguration(
                AdjustmentType="ChangeInCapacity",
                Cooldown=60,
                MetricAggregationType="Average",
                StepAdjustments=[
                    ts.applicationautoscaling.StepAdjustment(
                        MetricIntervalLowerBound=0,  # Relative to alarm value
                        ScalingAdjustment=1
                    )
                ]
            )
        ))

        self.image_processing_container_scale_down_policy = self._res(ts.applicationautoscaling.ScalingPolicy(
            "ImageProcessingContainerScaleDownPolicy",
            PolicyName="ImageProcessingContainerScaleDownPolicy",
            PolicyType="StepScaling",
            ScalingTargetId=self.image_processing_container_scaling_target.ref(),
            ScalableDimension="ecs:service:DesiredCount",
            ServiceNamespace="ecs",
            StepScalingPolicyConfiguration=ts.applicationautoscaling.StepScalingPolicyConfiguration(
                AdjustmentType="ChangeInCapacity",
                Cooldown=60,
                MetricAggregationType="Average",
                StepAdjustments=[
                    ts.applicationautoscaling.StepAdjustment(
                        MetricIntervalUpperBound=0,  # Relative to alarm value
                        ScalingAdjustment=-1
                    )
                ]
            )
        ))

        # Create instance scaling policies
        self.image_processing_scale_up_policy = self._res(ts.autoscaling.ScalingPolicy(
            "ImageProcessingScaleUpPolicy",
            AutoScalingGroupName=self.image_processing_auto_scaling_group.ref(),
            AdjustmentType="ChangeInCapacity",
            Cooldown=60,
            ScalingAdjustment=1
        ))

        self.image_processing_scale_down_policy = self._res(ts.autoscaling.ScalingPolicy(
            "ImageProcessingScaleDownPolicy",
            AutoScalingGroupName=self.image_processing_auto_scaling_group.ref(),
            AdjustmentType="ChangeInCapacity",
            Cooldown=60,
            ScalingAdjustment=-1
        ))

        # Create alarms
        self.image_processing_scale_up_alarm = self._res(ts.cloudwatch.Alarm(
            "ImageProcessingScaleUpAlarm",
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            Threshold=self.scale_up_threshold,
            Namespace="ImageProcessingService",
            MetricName="PipelineWaitingItems",
            Dimensions=[ts.cloudwatch.MetricDimension(
                Name="ClusterName",
                Value=ts.Select(1, ts.Split("/", self.image_processing_cluster.get_att("Arn"))))],
            Statistic="Average",
            Period=60,
            EvaluationPeriods=1,
            AlarmActions=[
                self.image_processing_container_scale_up_policy.ref(),
                self.image_processing_scale_up_policy.ref()
            ]
        ))

        self.image_processing_scale_down_alarm = self._res(ts.cloudwatch.Alarm(
            "ImageProcessingScaleDownAlarm",
            ComparisonOperator="LessThanThreshold",
            Threshold=self.scale_down_threshold,
            Namespace="ImageProcessingService",
            MetricName="PipelineWaitingItems",
            Dimensions=[ts.cloudwatch.MetricDimension(
                Name="ClusterName",
                Value=ts.Select(1, ts.Split("/", self.image_processing_cluster.get_att("Arn"))))],
            Statistic="Average",
            Period=60,
            EvaluationPeriods=2,
            AlarmActions=[
                self.image_processing_container_scale_down_policy.ref(),
                self.image_processing_scale_down_policy.ref()
            ]
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
