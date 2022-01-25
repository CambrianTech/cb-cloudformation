from collections import namedtuple
import troposphere as ts
import troposphere.iam
import troposphere.applicationautoscaling
import troposphere.cloudwatch
from .parameters import BackendParameters
from .cluster import BackendCluster


BackendScaling = namedtuple("BackendScaling", [
    "image_processing_container_scaling_role",
    "image_processing_container_scaling_target",
    "image_processing_container_scale_up_policy",
    "image_processing_container_scale_down_policy",
    "image_processing_scale_up_alarm",
    "image_processing_scale_down_alarm",
])


def create_scaling(
    template: ts.Template,
    params: BackendParameters,
    cluster: BackendCluster,
    ) -> BackendScaling:
    # Create role and target needed for container scaling
    image_processing_container_scaling_role = template.add_resource(ts.iam.Role(
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

    image_processing_container_scaling_target = template.add_resource(ts.applicationautoscaling.ScalableTarget(
        "ImageProcessingContainerScalingTarget",
        MinCapacity=params.min_instances.ref(),
        MaxCapacity=params.max_instances.ref(),
        ScalableDimension="ecs:service:DesiredCount",
        ServiceNamespace="ecs",
        ResourceId=ts.Join("/", [
            "service",
            cluster.image_processing_cluster.ref(),
            cluster.image_processing_service.get_att("Name")
        ]),
        RoleARN=image_processing_container_scaling_role.get_att("Arn")
    ))

    # Create container scaling policy
    image_processing_container_scale_up_policy = template.add_resource(ts.applicationautoscaling.ScalingPolicy(
        "ImageProcessingContainerScaleUpPolicy",
        PolicyName="ImageProcessingContainerScaleUpPolicy",
        PolicyType="StepScaling",
        ScalingTargetId=image_processing_container_scaling_target.ref(),
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

    image_processing_container_scale_down_policy = template.add_resource(ts.applicationautoscaling.ScalingPolicy(
        "ImageProcessingContainerScaleDownPolicy",
        PolicyName="ImageProcessingContainerScaleDownPolicy",
        PolicyType="StepScaling",
        ScalingTargetId=image_processing_container_scaling_target.ref(),
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
    image_processing_scale_up_alarm = template.add_resource(ts.cloudwatch.Alarm(
        "ImageProcessingScaleUpAlarm",
        ComparisonOperator="GreaterThanThreshold",
        Threshold=1.0,
        Namespace="ImageProcessingService",
        MetricName="BacklogPerInstance",
        Dimensions=[ts.cloudwatch.MetricDimension(
            Name="ClusterName",
            Value=ts.Select(1, ts.Split("/", cluster.image_processing_cluster.get_att("Arn"))))],
        Statistic="Average",
        Period=60,
        EvaluationPeriods=1,
        AlarmActions=[
            image_processing_container_scale_up_policy.ref(),
        ]
    ))

    image_processing_scale_down_alarm = template.add_resource(ts.cloudwatch.Alarm(
        "ImageProcessingScaleDownAlarm",
        ComparisonOperator="LessThanThreshold",
        Threshold=0.1,
        Namespace="ImageProcessingService",
        MetricName="BacklogPerInstance",
        Dimensions=[ts.cloudwatch.MetricDimension(
            Name="ClusterName",
            Value=ts.Select(1, ts.Split("/", cluster.image_processing_cluster.get_att("Arn"))))],
        Statistic="Average",
        Period=60,
        EvaluationPeriods=2,
        AlarmActions=[
            image_processing_container_scale_down_policy.ref(),
        ]
    ))

    return BackendScaling(
        image_processing_container_scaling_role,
        image_processing_container_scaling_target,
        image_processing_container_scale_up_policy,
        image_processing_container_scale_down_policy,
        image_processing_scale_up_alarm,
        image_processing_scale_down_alarm,
    )