import troposphere as ts
from troposphere import GetAtt
import troposphere.ec2
import troposphere.awslambda
import troposphere.iam
import troposphere.apigateway
import troposphere.s3
import troposphere.ecs
import troposphere.cloudformation
import troposphere.autoscaling
import troposphere.elasticloadbalancingv2
import troposphere.policies
import troposphere.ecr
import troposphere.helpers
import troposphere.helpers.userdata
import troposphere.logs
import troposphere.cloudwatch
import troposphere.applicationautoscaling
import troposphere.sqs
import troposphere.events


class BackendTemplateFactory:
    presigned_url_fn_name = "GetUserUploadPresignedUrl"
    backlog_fn_name = "PushBacklogMetric"

    image_processing_container_name = "ImageProcessingContainer"
    planes_container_name = "PlanesContainer"

    planes_port = 8081

    def create_template(self, cluster_key_name=None) -> ts.Template:
        self.cluster_key_name = cluster_key_name

        self.template = ts.Template("Cambrian image processing backend")

        self.ref_stack_id = ts.Ref("AWS::StackId")
        self.tags_stack_id = ts.Tags(Application=self.ref_stack_id)

        self._create_parameters()

        self._create_vpc()
        self._create_sqs()
        self._create_presigned_url_lambda()
        self._create_api_gateway()
        self._create_cluster()
        self._create_backlog_lambda()
        self._create_api_stage()
        self._create_scaling()

        return self.template

    def _res(self, resource):
        return self.template.add_resource(resource)

    def _map(self, name, mapping):
        return self.template.add_mapping(name, mapping)

    def _create_parameters(self):
        self.param_ecr_repository_name = self.template.add_parameter(ts.Parameter(
            "ImageProcessingServiceRepository",
            Type="String",
            Default="312943975091.dkr.ecr.us-east-1.amazonaws.com/cb-imageprocessingservice-api-3-dev-sqs:latest",
            Description="ECR Repository for the docker image to use."
        ))

        self.param_ecr_planes_repository_name = self.template.add_parameter(ts.Parameter(
            "PlanesServiceRepository",
            Type="String",
            Default="312943975091.dkr.ecr.us-east-1.amazonaws.com/cb-planes:latest",
            Description="ECR Repository for the planes docker image to use."
        ))

        self.param_image_processing_files_bucket_name = self.template.add_parameter(ts.Parameter(
            "ImageProcessingFilesBucket",
            Type="String",
            Default="cb-imageprocessingservice-models",
            Description="S3 bucket with the files (models etc.) that the container will download on startup."
        ))

        self.param_user_uploads_bucket_name = self.template.add_parameter(ts.Parameter(
            "ImageProcessingUserUploadsBucket",
            Type="String",
            Default="cb-backend-data",
            Description="S3 bucket where user uploaded content will be stored."
        ))

        self.param_image_processing_results_bucket_name = self.template.add_parameter(ts.Parameter(
            "ImageProcessingResultsBucket",
            Type="String",
            Default="cb-backend-data",
            Description="S3 bucket where processed images will be stored."
        ))

        self.param_min_instances = self.template.add_parameter(ts.Parameter(
            "MinimumInstances",
            Type="Number",
            Default=2,
            Description="Minimum number of instances and tasks for the cluster."
        ))

        self.param_max_instances = self.template.add_parameter(ts.Parameter(
            "MaximumInstances",
            Type="Number",
            Default=4,
            Description="Maximum number of instances and tasks for the cluster."
        ))

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
                          AvailabilityZone=ts.Sub("${AWS::Region}f"))
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

    def _create_presigned_url_lambda(self):
        # Create lambda execution role with S3 upload rights
        self.presigned_url_lambda_execution_role = self._res(
            ts.iam.Role(
                "GetUserUploadPresignedUrlExecutionRole",
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
                                "Resource": ts.Sub("arn:aws:s3:::${BucketName}/*", BucketName=self.param_user_uploads_bucket_name.ref()),
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

            return self._res(
                ts.awslambda.Function(
                    fn_name,
                    Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                    Handler="index.handler",
                    Environment=ts.awslambda.Environment(
                        Variables={
                            "BUCKET": bucket.ref()
                        }
                    ),
                    Role=self.presigned_url_lambda_execution_role.get_att("Arn"),
                    Runtime="nodejs14.x",
                    MemorySize=128,  # TODO: Make this param
                    Timeout=3  # TODO: Make this param
                )
            )

        # User upload
        self.presigned_url_lambda = _create_lambda("getuploadpresignedurl.js", self.presigned_url_fn_name, self.param_user_uploads_bucket_name)

    def _create_backlog_lambda(self):
        # - SQS GetQueueAttributes
        # - Autoscaling DescribeAutoScalingGroups
        # - CW PutMetricData
        self.backlog_lambda_execution_role = self._res(
            ts.iam.Role(
                "BacklogExecutionRole",
                DependsOn=[self.image_processing_queue.title],
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
                        PolicyName="SqsGetQueueAttributes",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [{
                                "Action": [
                                    "sqs:GetQueueAttributes",
                                ],
                                "Effect": "Allow",
                                "Resource": [
                                    GetAtt(self.image_processing_queue, "Arn"),
                                ]
                            }]
                        }
                    ),
                    ts.iam.Policy(
                        PolicyName="AutoscalingDescribeAutoScalingGroups",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [{
                                "Action": [
                                    "autoscaling:DescribeAutoScalingGroups",
                                ],
                                "Effect": "Allow",
                                "Resource": "*" # TODO: Figure out way to get ASG ARN
                            }]
                        }
                    ),
                    ts.iam.Policy(
                        PolicyName="CWPutMetricData",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [{
                                "Action": [
                                    "cloudwatch:PutMetricData",
                                ],
                                "Effect": "Allow",
                                "Resource": "*"
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

        with open("pushbacklogmetric.js", "r") as code_file:
            code_lines = code_file.readlines()

        self.backlog_lambda = self._res(
            ts.awslambda.Function(
                self.backlog_fn_name,
                DependsOn=[
                    self.image_processing_queue.title,
                    self.image_processing_auto_scaling_group.title,
                    self.image_processing_cluster.title,
                    self.backlog_lambda_execution_role.title,
                ],
                Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                Handler="index.handler",
                Environment=ts.awslambda.Environment(
                    Variables={
                        "QUEUE_URL": self.image_processing_queue.ref(),
                        "AUTOSCALINGGROUP_NAME": self.image_processing_auto_scaling_group.ref(),
                        "CLUSTER_NAME": self.image_processing_cluster.ref(),
                    }
                ),
                Role=self.backlog_lambda_execution_role.get_att("Arn"),
                Runtime="nodejs14.x",
                MemorySize=128,  # TODO: Make this param
                Timeout=3  # TODO: Make this param
            )
        )

        self.backlog_lambda_schedule = self._res(
            ts.events.Rule(
                "%sSchedule" % self.backlog_fn_name,
                DependsOn=[
                    self.backlog_lambda.title,
                ],
                ScheduleExpression="rate(1 minute)",
                Targets=[
                    ts.events.Target(
                        "%sScheduleTarget" % self.backlog_fn_name,
                        Arn=self.backlog_lambda.get_att("Arn"),
                        Id="1"
                    )
                ]
            )
        )

        self.backlog_lambda_schedule_permission = self._res(
            ts.awslambda.Permission(
                "%sSchedulePermission" % self.backlog_fn_name,
                DependsOn=[
                    self.backlog_lambda.title,
                    self.backlog_lambda_schedule.title,
                ],
                Action="lambda:InvokeFunction",
                FunctionName=self.backlog_lambda.get_att("Arn"),
                Principal="events.amazonaws.com",
                SourceArn=self.backlog_lambda_schedule.get_att("Arn"),
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

        def _add_lambda(l, name, fn_name):
            # Create lambda permissions for api gateway
            permissions = self._res(
                ts.awslambda.Permission(
                    "RestApiGet" + name + "PresignedUrlPermissions",
                    Action="lambda:invokeFunction",
                    Principal="apigateway.amazonaws.com",
                    FunctionName=l.get_att("Arn"),
                    SourceArn=ts.Sub("arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${apiName}/*/*/${funcName}",
                                    apiName=self.rest_api.ref(), funcName=fn_name)
                )
            )

            api = self._res(
                ts.apigateway.Resource(
                    "Get" + name + "PresignedUrlRestApiResource",
                    ParentId=self.rest_api.get_att("RootResourceId"),
                    RestApiId=self.rest_api.ref(),
                    PathPart='Get' + name + 'PresignedUrl'
                )
            )

            method = self._res(
                ts.apigateway.Method(
                    "Get" + name + "PresignedUrlRestApiMethod",
                    DependsOn=l.title,
                    HttpMethod="GET",
                    ResourceId=api.ref(),
                    RestApiId=self.rest_api.ref(),
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

        self.rest_api_get_presigned_permissions, self.api_get_presigned, self.api_get_presigned_method = _add_lambda(self.presigned_url_lambda, "UserUpload", self.presigned_url_fn_name)

        # Wire up load balancer with api gateway (url/ImageProcessing/*)
        self.api_image_processing = self._res(
            ts.apigateway.Resource(
                "ImageProcessingRestApiResource",
                ParentId=self.rest_api.get_att("RootResourceId"),
                RestApiId=self.rest_api.ref(),
                PathPart="ImageProcessing"
            )
        )

        self.api_image_processing_segment_resource = self._res(
            ts.apigateway.Resource(
                "ImageProcessingSegmentResource",
                ParentId=self.api_image_processing.ref(),
                RestApiId=self.rest_api.ref(),
                PathPart="segment"
            )
        )

        self.api_image_processing_segment_key_resource = self._res(
            ts.apigateway.Resource(
                "ImageProcessingSegmentKeyResource",
                ParentId=self.api_image_processing_segment_resource.ref(),
                RestApiId=self.rest_api.ref(),
                PathPart="{key}"
            )
        )

        self.api_image_processing_segment_role = self._res(
            ts.iam.Role(
                "ImageProcessingProcessRole",
                DependsOn=[self.image_processing_queue.title],
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
                                    GetAtt(self.image_processing_queue, "Arn"),
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

        self.api_image_processing_method = self._res(
            ts.apigateway.Method(
                "ImageProcessingMethod",
                DependsOn=[
                    self.api_image_processing_segment_role.title,
                    self.image_processing_queue.title,
                    self.api_image_processing_segment_key_resource.title,
                ],
                HttpMethod="GET",
                ResourceId=self.api_image_processing_segment_key_resource.ref(),
                RestApiId=self.rest_api.ref(),
                AuthorizationType="NONE",
                RequestParameters={
                    "method.request.querystring.MessageBody": False,
                },
                Integration=ts.apigateway.Integration(
                    Type="AWS",
                    Credentials=GetAtt(self.api_image_processing_segment_role, "Arn"),
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
                        "integration.request.querystring.QueueUrl": ts.Join("", ["'", self.image_processing_queue.ref(), "'"]),
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

    def _create_sqs(self):
        self.image_processing_queue = self._res(ts.sqs.Queue(
            "ImageProcessingQueue",
            FifoQueue=True,
            VisibilityTimeout=300,
            ContentBasedDeduplication=True,
        ))

    def _create_cluster(self):
        # Create cluster
        self.image_processing_cluster = self._res(ts.ecs.Cluster(
            "ImageProcessingCluster",
            DependsOn=self.vpc.title
        ))

        self.image_processing_instance_id_mapping = self._map("ImageProcessingInstanceId", {
            # ECS GPU optimized AMI IDs. Add more regions here if necessary.
            # https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html
            # Currently using a custom image based on the ECS-optimized GPU image to ensure all
            # containers run with the nvidia runtime in order to share GPUs between them.
            # See https://github.com/aws/containers-roadmap/issues/327#issuecomment-471162879
            "us-east-1": {"AMI": "ami-078703383d34ae5ba"},
            "us-east-2": {"AMI": "ami-0c45dd0e1ef99bcf2"},
            "us-west-1": {"AMI": "ami-0ddd4f56f0468c9c4"},
            "us-west-2": {"AMI": "ami-0a36be2e955646bb2"},
        })

        sg_rules = [
            ts.ec2.SecurityGroupRule(
                "ImageProcessingLoadBalancerSGIngress",
                CidrIp="0.0.0.0/0",
                IpProtocol="tcp",
                FromPort=8080,
                ToPort=8080
            )
        ]

        launch_config_args = {}
        if self.cluster_key_name is not None:
            print("Warning: allowing ssh connection to cluster")
            sg_rules.append(ts.ec2.SecurityGroupRule(
                "ImageProcessingLoadBalancerSGIngress",
                CidrIp="0.0.0.0/0",
                IpProtocol="tcp",
                FromPort=22,
                ToPort=22
            ))
            launch_config_args["KeyName"] = self.cluster_key_name

        self.image_processing_instance_sg = self._res(ts.ec2.SecurityGroup(
            "ImageProcessingInstanceSG",
            GroupDescription="Allow TCP traffic on 8080",
            VpcId=self.vpc.ref(),
            SecurityGroupIngress=sg_rules
        ))


        self.image_processing_launch_config = self._res(ts.autoscaling.LaunchConfiguration(
            "ImageProcessingLaunchConfiguration",
            **launch_config_args,
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
                                    " >> /etc/ecs/ecs.config\n",
                                    "echo ECS_ENGINE_TASK_CLEANUP_WAIT_DURATION=10m",
                                    " >> /etc/ecs/ecs.config\n",
                                    "echo ECS_IMAGE_CLEANUP_INTERVAL=10m",
                                    " >> /etc/ecs/ecs.config\n",
                                    "echo ECS_IMAGE_MINIMUM_CLEANUP_AGE=10m",
                                    " >> /etc/ecs/ecs.config\n",
                                    "echo 'OPTIONS=\"${OPTIONS} --storage-opt dm.basesize=20G\"'",
                                    " >> /etc/sysconfig/docker\n"
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
            InstanceType="g4dn.2xlarge",
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
            DependsOn=[self.image_processing_cluster.title],
            VPCZoneIdentifier=[self.pub_sub.ref(), self.pub_sub2.ref()],
            LaunchConfigurationName=self.image_processing_launch_config.ref(),
            MinSize=self.param_min_instances.ref(),
            MaxSize=self.param_max_instances.ref(),
            NewInstancesProtectedFromScaleIn=True,

            # Wait 5 minutes before timing out when not receiving health signal
            CreationPolicy=ts.policies.CreationPolicy(
                ResourceSignal=ts.policies.ResourceSignal(
                    Timeout="PT5M",
                    Count=self.param_min_instances.ref(),
                )
            ),
            UpdatePolicy=ts.policies.UpdatePolicy(
                AutoScalingRollingUpdate=ts.policies.AutoScalingRollingUpdate(
                    MinSuccessfulInstancesPercent=100,
                    PauseTime="PT5M",
                    WaitOnResourceSignals=True,
                    SuspendProcesses=[
                        "AddToLoadBalancer",
                        "AlarmNotification",
                        "AZRebalance",
                        "HealthCheck",
                        "ReplaceUnhealthy",
                        "ScheduleActions",
                    ]
                )
            )
        ))

        self.cluster_capacity_provider = self._res(ts.ecs.CapacityProvider(
            "ImageProcessingClusterCapacityProvider",
            DependsOn=[self.image_processing_cluster.title],
            AutoScalingGroupProvider=troposphere.ecs.AutoScalingGroupProvider(
                AutoScalingGroupArn=self.image_processing_auto_scaling_group.ref(),
                ManagedScaling=troposphere.ecs.ManagedScaling(
                    Status="ENABLED",
                    TargetCapacity=100,
                ),
                ManagedTerminationProtection="ENABLED",
            ),
        ))

        self.cluster_capacity_provider_associations = self._res(ts.ecs.ClusterCapacityProviderAssociations(
            "ImageProcessingClusterCapacityProviderAssociations",
            Cluster=self.image_processing_cluster.ref(),
            CapacityProviders=[self.cluster_capacity_provider.ref()],
            DefaultCapacityProviderStrategy=[troposphere.ecs.CapacityProviderStrategy(
                CapacityProvider=self.cluster_capacity_provider.ref(),
                Weight=1,
            )],
        ))

        self.image_processing_instance_role = self._res(ts.iam.Role(
            "ImageProcessingInstanceRole",
            DependsOn=[self.image_processing_queue.title],
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
                    PolicyName="ImageProcessingInstancePolicySQS",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": [
                                "sqs:GetQueueAttributes",
                                "sqs:GetQueueUrl",
                                "sqs:ReceiveMessage",
                                "sqs:DeleteMessage",
                            ],
                            "Effect": "Allow",
                            "Resource": [
                                GetAtt(self.image_processing_queue, "Arn"),
                            ]
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
                                ts.Sub("arn:aws:s3:::${FilesBucketName}", FilesBucketName=self.param_image_processing_files_bucket_name.ref()),
                                ts.Sub("arn:aws:s3:::${FilesBucketName}/*", FilesBucketName=self.param_image_processing_files_bucket_name.ref()),
                                ts.Sub("arn:aws:s3:::${UserUploadsBucketName}", UserUploadsBucketName=self.param_user_uploads_bucket_name.ref()),
                                ts.Sub("arn:aws:s3:::${UserUploadsBucketName}/*", UserUploadsBucketName=self.param_user_uploads_bucket_name.ref()),
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
                                ts.Sub("arn:aws:s3:::${ResultsBucketName}/*", ResultsBucketName=self.param_image_processing_results_bucket_name.ref()),
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

        self.image_processing_log_group = self._res(ts.logs.LogGroup(
            "ImageProcessingLogGroup",
            RetentionInDays=14,
            DeletionPolicy="Retain"
        ))

        self.image_processing_task_def = self._res(ts.ecs.TaskDefinition(
            "ImageProcessingTaskDefinition",
            DependsOn=[self.image_processing_queue.title],
            ContainerDefinitions=[
                ts.ecs.ContainerDefinition(
                    Name=self.image_processing_container_name,
                    Essential=True,
                    PortMappings=[ts.ecs.PortMapping(
                        HostPort=8080,
                        ContainerPort=8080
                    )],
                    MemoryReservation=10000,
                    ResourceRequirements=[
                        # Can't currently share GPUs in ECS this way, so we're using
                        # a custom AMI that uses the nvidia runtime for all containers
                        # which will automatically share all GPUs.
                        #ts.ecs.ResourceRequirement(Type="GPU", Value="1")
                    ],
                    Image=self.param_ecr_repository_name.ref(),
                    LogConfiguration=ts.ecs.LogConfiguration(
                        LogDriver="awslogs",
                        Options={
                            "awslogs-group": self.image_processing_log_group.ref(),
                            "awslogs-region": ts.Ref(ts.AWS_REGION),
                            "awslogs-stream-prefix": "image-processing-service"
                        }
                    ),
                    Environment=[
                        ts.ecs.Environment(Name="FILES_BUCKET", Value=self.param_image_processing_files_bucket_name.ref()),
                        ts.ecs.Environment(Name="USER_UPLOADS_BUCKET", Value=self.param_user_uploads_bucket_name.ref()),
                        ts.ecs.Environment(Name="RESULTS_BUCKET", Value=self.param_image_processing_results_bucket_name.ref()),
                        ts.ecs.Environment(Name="PLANES_ADDRESS", Value="http://%s:%d" % (self.planes_container_name, self.planes_port)),
                        ts.ecs.Environment(Name="SQS_QUEUE_NAME", Value=GetAtt(self.image_processing_queue, "QueueName")),
                    ],
                    Links=[self.planes_container_name],
                    HealthCheck=troposphere.ecs.HealthCheck(
                        Command=["CMD-SHELL", "curl -f http://localhost:8080/healthcheck || exit 1"],
                        Interval=45,
                        Retries=10,
                        Timeout=5,
                    ),
                ),
                ts.ecs.ContainerDefinition(
                    Name=self.planes_container_name,
                    Essential=True,
                    PortMappings=[ts.ecs.PortMapping(
                        HostPort=self.planes_port,
                        ContainerPort=self.planes_port
                    )],
                    MemoryReservation=10000,
                    ResourceRequirements=[
                        ts.ecs.ResourceRequirement(Type="GPU", Value="1")
                    ],
                    Image=self.param_ecr_planes_repository_name.ref(),
                    LogConfiguration=ts.ecs.LogConfiguration(
                        LogDriver="awslogs",
                        Options={
                            "awslogs-group": self.image_processing_log_group.ref(),
                            "awslogs-region": ts.Ref(ts.AWS_REGION),
                            "awslogs-stream-prefix": "planes-service"
                        }
                    )
                )
            ]
        ))

        # Create ECS service on cluster
        self.image_processing_service = self._res(ts.ecs.Service(
            "ImageProcessingService",
            DependsOn=[
                self.image_processing_auto_scaling_group.title,
                self.cluster_capacity_provider.title,
                self.image_processing_cluster.title,
            ],
            Cluster=self.image_processing_cluster.ref(),
            DesiredCount=self.param_min_instances.ref(),
            DeploymentConfiguration=ts.ecs.DeploymentConfiguration(
                MaximumPercent=100,
                MinimumHealthyPercent=0  # 0% Needed for dev updates
            ),
            TaskDefinition=self.image_processing_task_def.ref(),
            CapacityProviderStrategy=[
                troposphere.ecs.CapacityProviderStrategyItem(
                    CapacityProvider=self.cluster_capacity_provider.ref(),
                    Weight=1,
                ),
            ]
        ))

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
            MinCapacity=self.param_min_instances.ref(),
            MaxCapacity=self.param_max_instances.ref(),
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
                Cooldown=300,
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
                Cooldown=300,
                MetricAggregationType="Average",
                StepAdjustments=[
                    ts.applicationautoscaling.StepAdjustment(
                        MetricIntervalUpperBound=0,  # Relative to alarm value
                        ScalingAdjustment=-1
                    )
                ]
            )
        ))

        # Create alarms
        self.image_processing_scale_up_alarm = self._res(ts.cloudwatch.Alarm(
            "ImageProcessingScaleUpAlarm",
            ComparisonOperator="GreaterThanThreshold",
            Threshold=1.0,
            Namespace="ImageProcessingService",
            MetricName="BacklogPerInstance",
            Dimensions=[ts.cloudwatch.MetricDimension(
                Name="ClusterName",
                Value=ts.Select(1, ts.Split("/", self.image_processing_cluster.get_att("Arn"))))],
            Statistic="Average",
            Period=60,
            EvaluationPeriods=1,
            AlarmActions=[
                self.image_processing_container_scale_up_policy.ref(),
            ]
        ))

        self.image_processing_scale_down_alarm = self._res(ts.cloudwatch.Alarm(
            "ImageProcessingScaleDownAlarm",
            ComparisonOperator="LessThanThreshold",
            Threshold=0.1,
            Namespace="ImageProcessingService",
            MetricName="BacklogPerInstance",
            Dimensions=[ts.cloudwatch.MetricDimension(
                Name="ClusterName",
                Value=ts.Select(1, ts.Split("/", self.image_processing_cluster.get_att("Arn"))))],
            Statistic="Average",
            Period=60,
            EvaluationPeriods=2,
            AlarmActions=[
                self.image_processing_container_scale_down_policy.ref(),
            ]
        ))


def main():
    template_factory = BackendTemplateFactory()

    def _write_template(path):
        print("-- Writing backend template to", path)
        template = template_factory.create_template()

        template_yaml = template.to_yaml()

        with open(path, "w") as output_file:
            output_file.write(template_yaml)

    _write_template("backend.yml")


if __name__ == "__main__":
    main()
