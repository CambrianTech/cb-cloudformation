from collections import namedtuple
from pathlib import Path
import troposphere as ts
import troposphere.iam
import troposphere.awslambda
import troposphere.events
from .cluster import BackendCluster
from .sqs import BackendSqs
from .constants import backlog_fn_name


BackendBacklogLambda = namedtuple("BackendBacklogLambda", [
    "backlog_lambda_execution_role",
    "backlog_lambda",
    "backlog_lambda_schedule",
    "backlog_lambda_schedule_permission",
])


def create_backlog_lambda(
    template: ts.Template,
    sqs: BackendSqs,
    cluster: BackendCluster,
    ) -> BackendBacklogLambda:
    # - SQS GetQueueAttributes
    # - Autoscaling DescribeAutoScalingGroups
    # - CW PutMetricData
    backlog_lambda_execution_role = template.add_resource(
        ts.iam.Role(
            "BacklogExecutionRole",
            DependsOn=[sqs.image_processing_queue.title],
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
                                sqs.image_processing_queue.get_att("Arn"),
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

    script_path = Path(__file__).resolve().parent / "lambdas" / "pushbacklogmetric.js"
    with open(script_path, "r") as code_file:
        code_lines = code_file.readlines()

    backlog_lambda = template.add_resource(
        ts.awslambda.Function(
            backlog_fn_name,
            DependsOn=[
                sqs.image_processing_queue.title,
                cluster.image_processing_auto_scaling_group.title,
                cluster.image_processing_cluster.title,
                backlog_lambda_execution_role.title,
            ],
            Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
            Handler="index.handler",
            Environment=ts.awslambda.Environment(
                Variables={
                    "QUEUE_URL": sqs.image_processing_queue.ref(),
                    "AUTOSCALINGGROUP_NAME": cluster.image_processing_auto_scaling_group.ref(),
                    "CLUSTER_NAME": cluster.image_processing_cluster.ref(),
                }
            ),
            Role=backlog_lambda_execution_role.get_att("Arn"),
            Runtime="nodejs14.x",
            MemorySize=128,  # TODO: Make this param
            Timeout=3  # TODO: Make this param
        )
    )

    backlog_lambda_schedule = template.add_resource(
        ts.events.Rule(
            "%sSchedule" % backlog_fn_name,
            DependsOn=[
                backlog_lambda.title,
            ],
            ScheduleExpression="rate(1 minute)",
            Targets=[
                ts.events.Target(
                    "%sScheduleTarget" % backlog_fn_name,
                    Arn=backlog_lambda.get_att("Arn"),
                    Id="1"
                )
            ]
        )
    )

    backlog_lambda_schedule_permission = template.add_resource(
        ts.awslambda.Permission(
            "%sSchedulePermission" % backlog_fn_name,
            DependsOn=[
                backlog_lambda.title,
                backlog_lambda_schedule.title,
            ],
            Action="lambda:InvokeFunction",
            FunctionName=backlog_lambda.get_att("Arn"),
            Principal="events.amazonaws.com",
            SourceArn=backlog_lambda_schedule.get_att("Arn"),
        )
    )

    return BackendBacklogLambda(
        backlog_lambda_execution_role,
        backlog_lambda,
        backlog_lambda_schedule,
        backlog_lambda_schedule_permission,
    )