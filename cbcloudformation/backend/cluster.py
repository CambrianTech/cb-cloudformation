from collections import namedtuple
import troposphere as ts
import troposphere.ec2
import troposphere.iam
import troposphere.awslambda
import troposphere.autoscaling
import troposphere.policies
import troposphere.ecs
import troposphere.logs
from .network import BackendNetwork
from .parameters import BackendParameters
from .sqs import BackendSqs
from .constants import planes_container_name, planes_port, image_processing_container_name


BackendCluster = namedtuple("BackendCluster", [
    "image_processing_cluster",
    "image_processing_instance_id_mapping",
    "sg_rules",
    "image_processing_instance_sg",
    "image_processing_launch_config",
    "image_processing_auto_scaling_group",
    "cluster_capacity_provider",
    "cluster_capacity_provider_associations",
    "image_processing_instance_role",
    "image_processing_instance_profile",
    "image_processing_log_group",
    "image_processing_task_def",
    "image_processing_service",
])


def create_cluster(
    template: ts.Template,
    params: BackendParameters,
    network: BackendNetwork,
    sqs: BackendSqs
    ) -> BackendCluster:
    # Create cluster
    image_processing_cluster = template.add_resource(ts.ecs.Cluster(
        "ImageProcessingCluster",
        DependsOn=network.vpc.title
    ))

    image_processing_instance_id_mapping = template.add_mapping("ImageProcessingInstanceId", {
        # ECS GPU optimized AMI IDs. Add more regions here if necessary.
        # https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html
        # Currently using a custom image based on the ECS-optimized GPU image to ensure all
        # containers run with the nvidia runtime in order to share GPUs between them.
        # See https://github.com/aws/containers-roadmap/issues/327#issuecomment-471162879
        "us-east-1": {"AMI": "ami-0817bd404ae50f662"},
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

    image_processing_instance_sg = template.add_resource(ts.ec2.SecurityGroup(
        "ImageProcessingInstanceSG",
        GroupDescription="Allow TCP traffic on 8080",
        VpcId=network.vpc.ref(),
        SecurityGroupIngress=sg_rules
    ))

    image_processing_launch_config = template.add_resource(ts.autoscaling.LaunchConfiguration(
        "ImageProcessingLaunchConfiguration",
        Metadata=ts.autoscaling.Metadata(
            ts.cloudformation.Init({
                "config": ts.cloudformation.InitConfig(
                    commands={
                        "01_add_instance_to_cluster": {
                            "command": ts.Join("", [
                                "#!/bin/bash\n",
                                "echo ECS_CLUSTER=",
                                image_processing_cluster.ref(),
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
        InstanceType="g5.2xlarge",
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
        SecurityGroups=[image_processing_instance_sg.ref()],
        # necessary for 1 minute metrics (5 minute is default)
        InstanceMonitoring=True,
        AssociatePublicIpAddress=True,
    ))

    image_processing_auto_scaling_group = template.add_resource(ts.autoscaling.AutoScalingGroup(
        "ImageProcessingAutoScalingGroup",
        DependsOn=[image_processing_cluster.title],
        VPCZoneIdentifier=[network.pub_sub.ref(), network.pub_sub2.ref()],
        LaunchConfigurationName=image_processing_launch_config.ref(),
        MinSize=params.min_instances.ref(),
        MaxSize=params.max_instances.ref(),
        NewInstancesProtectedFromScaleIn=True,

        # Wait 5 minutes before timing out when not receiving health signal
        CreationPolicy=ts.policies.CreationPolicy(
            ResourceSignal=ts.policies.ResourceSignal(
                Timeout="PT5M",
                Count=params.min_instances.ref(),
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

    cluster_capacity_provider = template.add_resource(ts.ecs.CapacityProvider(
        "ImageProcessingClusterCapacityProvider",
        DependsOn=[image_processing_cluster.title],
        AutoScalingGroupProvider=ts.ecs.AutoScalingGroupProvider(
            AutoScalingGroupArn=image_processing_auto_scaling_group.ref(),
            ManagedScaling=ts.ecs.ManagedScaling(
                Status="ENABLED",
                TargetCapacity=100,
            ),
            ManagedTerminationProtection="ENABLED",
        ),
    ))
    
    cluster_capacity_provider_associations = template.add_resource(ts.ecs.ClusterCapacityProviderAssociations(
        "ImageProcessingClusterCapacityProviderAssociations",
        DependsOn=[
            image_processing_cluster.title,
            cluster_capacity_provider.title,
        ],
        Cluster=image_processing_cluster.ref(),
        CapacityProviders=[cluster_capacity_provider.ref()],
        DefaultCapacityProviderStrategy=[ts.ecs.CapacityProviderStrategy(
            CapacityProvider=cluster_capacity_provider.ref(),
            Base=1,
            Weight=1,
        )],
    ))

    image_processing_instance_role = template.add_resource(ts.iam.Role(
        "ImageProcessingInstanceRole",
        DependsOn=[sqs.image_processing_queue.title],
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
                            sqs.image_processing_queue.get_att("Arn"),
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
                            ts.Sub("arn:aws:s3:::${FilesBucketName}", FilesBucketName=params.image_processing_files_bucket_name.ref()),
                            ts.Sub("arn:aws:s3:::${FilesBucketName}/*", FilesBucketName=params.image_processing_files_bucket_name.ref()),
                            ts.Sub("arn:aws:s3:::${UserUploadsBucketName}", UserUploadsBucketName=params.user_uploads_bucket_name.ref()),
                            ts.Sub("arn:aws:s3:::${UserUploadsBucketName}/*", UserUploadsBucketName=params.user_uploads_bucket_name.ref()),
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
                            ts.Sub("arn:aws:s3:::${ResultsBucketName}/*", ResultsBucketName=params.image_processing_results_bucket_name.ref()),
                        ]
                    }]
                }
            ),
        ]
    ))

    image_processing_instance_profile = template.add_resource(ts.iam.InstanceProfile(
        "ImageProcessingInstanceProfile",
        Path="/",
        Roles=[image_processing_instance_role.ref()]
    ))

    image_processing_log_group = template.add_resource(ts.logs.LogGroup(
        "ImageProcessingLogGroup",
        RetentionInDays=14,
        DeletionPolicy="Retain"
    ))

    image_processing_task_def = template.add_resource(ts.ecs.TaskDefinition(
        "ImageProcessingTaskDefinition",
        DependsOn=[sqs.image_processing_queue.title],
        ContainerDefinitions=[
            ts.ecs.ContainerDefinition(
                Name=image_processing_container_name,
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
                Image=params.ecr_repository_name.ref(),
                LogConfiguration=ts.ecs.LogConfiguration(
                    LogDriver="awslogs",
                    Options={
                        "awslogs-group": image_processing_log_group.ref(),
                        "awslogs-region": ts.Ref(ts.AWS_REGION),
                        "awslogs-stream-prefix": "image-processing-service"
                    }
                ),
                Environment=[
                    ts.ecs.Environment(Name="FILES_BUCKET", Value=params.image_processing_files_bucket_name.ref()),
                    ts.ecs.Environment(Name="USER_UPLOADS_BUCKET", Value=params.user_uploads_bucket_name.ref()),
                    ts.ecs.Environment(Name="RESULTS_BUCKET", Value=params.image_processing_results_bucket_name.ref()),
                    ts.ecs.Environment(Name="PLANES_ADDRESS", Value="http://%s:%d" % (planes_container_name, planes_port)),
                    ts.ecs.Environment(Name="SQS_QUEUE_NAME", Value=sqs.image_processing_queue.get_att("QueueName")),
                ],
                Links=[planes_container_name],
                HealthCheck=ts.ecs.HealthCheck(
                    Command=["CMD-SHELL", "curl -f http://localhost:8080/healthcheck || exit 1"],
                    Interval=45,
                    Retries=10,
                    Timeout=5,
                ),
            ),
            ts.ecs.ContainerDefinition(
                Name=planes_container_name,
                Essential=True,
                PortMappings=[ts.ecs.PortMapping(
                    HostPort=planes_port,
                    ContainerPort=planes_port
                )],
                MemoryReservation=10000,
                ResourceRequirements=[
                    ts.ecs.ResourceRequirement(Type="GPU", Value="1")
                ],
                Image=params.ecr_planes_repository_name.ref(),
                LogConfiguration=ts.ecs.LogConfiguration(
                    LogDriver="awslogs",
                    Options={
                        "awslogs-group": image_processing_log_group.ref(),
                        "awslogs-region": ts.Ref(ts.AWS_REGION),
                        "awslogs-stream-prefix": "planes-service"
                    }
                )
            )
        ]
    ))

    # Create ECS service on cluster
    image_processing_service = template.add_resource(ts.ecs.Service(
        "ImageProcessingService",
        DependsOn=[
            image_processing_auto_scaling_group.title,
            cluster_capacity_provider.title,
            image_processing_cluster.title,
        ],
        Cluster=image_processing_cluster.ref(),
        DesiredCount=params.min_instances.ref(),
        DeploymentConfiguration=ts.ecs.DeploymentConfiguration(
            MaximumPercent=100,
            MinimumHealthyPercent=0  # 0% Needed for dev updates
        ),
        TaskDefinition=image_processing_task_def.ref(),
        CapacityProviderStrategy=[
            ts.ecs.CapacityProviderStrategyItem(
                CapacityProvider=cluster_capacity_provider.ref(),
                Base=1,
                Weight=1,
            ),
        ]
    ))

    return BackendCluster(
        image_processing_cluster,
        image_processing_instance_id_mapping,
        sg_rules,
        image_processing_instance_sg,
        image_processing_launch_config,
        image_processing_auto_scaling_group,
        cluster_capacity_provider,
        cluster_capacity_provider_associations,
        image_processing_instance_role,
        image_processing_instance_profile,
        image_processing_log_group,
        image_processing_task_def,
        image_processing_service,
    )