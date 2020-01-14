import troposphere as ts
import troposphere.codepipeline
import troposphere.sns
import troposphere.codebuild
import troposphere.iam
from random import randint


class FrontendTemplateFactory:
    def create_template(self) -> ts.Template:
        self.template = ts.Template(
            "Frontend deployment pipeline with approval process")

        self.random_id = randint(0, 100000000)

        self._create_parameters()
        self._create_permissions()
        self._create_source_stage()
        self._create_build_stage()
        self._create_approve_stage()
        self._create_deploy_stage()
        self._create_pipeline()

        return self.template

    def _res(self, resource):
        return self.template.add_resource(resource)

    def _create_parameters(self):
        self.param_env_file_bucket = self.template.add_parameter(ts.Parameter(
            "EnvFileBucket",
            Type="String",
            Default="cb-codebuild-env-files",
            Description="S3 bucket where zipped env files are stored. Needs to have versioning enabled."
        ))

        self.param_env_file_path = self.template.add_parameter(ts.Parameter(
            "EnvFilePath",
            Type="String",
            Default="dev.zip",
            Description="Path within the env file S3 bucket to the zipped env files."
        ))

        self.param_codepipeline_bucket = self.template.add_parameter(ts.Parameter(
            "CodePipelineBucket",
            Type="String",
            Default="codepipeline-us-east-1-403239856615",
            Description="S3 Bucket used by codepipeline. Needs to have block all public access off."
        ))

        self.param_ecr_repo_name = self.template.add_parameter(ts.Parameter(
            "ECRRepoName",
            Type="String",
            Default="312943975091.dkr.ecr.us-east-1.amazonaws.com/cb-shaw-frontend-dev",
            Description="The full ECR repository URI to push the frontend image to."
        ))

        self.param_beanstalk_staging_app = self.template.add_parameter(ts.Parameter(
            "ElasticBeanstalkStagingApp",
            Type="String",
            Default="shaw-frontend-dev",
            Description="Elastic Beanstalk staging application."
        ))

        self.param_beanstalk_staging_env = self.template.add_parameter(ts.Parameter(
            "ElasticBeanstalkStagingEnv",
            Type="String",
            Default="shaw-frontend-dev-staging",
            Description="Elastic Beanstalk staging environment."
        ))

        self.param_beanstalk_staging_url = self.template.add_parameter(ts.Parameter(
            "ElasticBeanstalkStagingUrl",
            Type="String",
            Default="https://dev-staging.cambrianar.com",
            Description="Url that is shown in the notification for the deployment approval process. Should be the url that points to the staging website."
        ))

        self.param_beanstalk_prod_app = self.template.add_parameter(ts.Parameter(
            "ElasticBeanstalkProductionApp",
            Type="String",
            Default="shaw-frontend-dev",
            Description="Elastic Beanstalk production application."
        ))

        self.param_beanstalk_prod_env = self.template.add_parameter(ts.Parameter(
            "ElasticBeanstalkProductionEnv",
            Type="String",
            Default="shaw-frontend-dev-main",
            Description="Elastic Beanstalk production environment."
        ))

        self.param_github_owner = self.template.add_parameter(ts.Parameter(
            "GitHubOwner",
            Type="String",
            Default="CambrianTech",
            Description="Owning organization or user of the GitHub repository."
        ))

        self.param_github_repo = self.template.add_parameter(ts.Parameter(
            "GitHubRepo",
            Type="String",
            Default="shaw-frontend",
            Description="Name of the GitHub repository."
        ))

        self.param_github_branch = self.template.add_parameter(ts.Parameter(
            "GitHubBranch",
            Type="String",
            Default="feature/ebenv",
            Description="Branch of the GitHub repository."
        ))

        self.param_github_oauth = self.template.add_parameter(ts.Parameter(
            "GitHubOAuthToken",
            Type="String",
            Default="25e6bd223c762f0dcdc54c698a2436bb50bcab49",
            Description="OAuth Token for accessing the GitHub repository. See https://docs.aws.amazon.com/codebuild/latest/userguide/sample-access-tokens.html for more information."
        ))

    def _create_permissions(self):
        self.pipeline_role = self._res(ts.iam.Role(
            "PipelineRole",
            RoleName=ts.Sub(
                "AWSCodePipelineServiceRole-${AWS::Region}-Frontend-${Id}", Id=self.random_id),
            Path="/service-role/",
            Policies=[ts.iam.Policy(
                PolicyName=ts.Sub(
                    "AWSCodePipelineServiceRole-${AWS::Region}-Frontend-${Id}", Id=self.random_id),
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": [
                                "iam:PassRole"
                            ],
                            "Resource": "*",
                            "Effect": "Allow",
                            "Condition": {
                                "StringEqualsIfExists": {
                                    "iam:PassedToService": [
                                        "cloudformation.amazonaws.com",
                                        "elasticbeanstalk.amazonaws.com",
                                        "ec2.amazonaws.com",
                                        "ecs-tasks.amazonaws.com"
                                    ]
                                }
                            }
                        },
                        {
                            "Action": [
                                "codecommit:CancelUploadArchive",
                                "codecommit:GetBranch",
                                "codecommit:GetCommit",
                                "codecommit:GetUploadArchiveStatus",
                                "codecommit:UploadArchive"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "codedeploy:CreateDeployment",
                                "codedeploy:GetApplication",
                                "codedeploy:GetApplicationRevision",
                                "codedeploy:GetDeployment",
                                "codedeploy:GetDeploymentConfig",
                                "codedeploy:RegisterApplicationRevision"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "elasticbeanstalk:*",
                                "ec2:*",
                                "elasticloadbalancing:*",
                                "autoscaling:*",
                                "cloudwatch:*",
                                "s3:*",
                                "sns:*",
                                "cloudformation:*",
                                "rds:*",
                                "sqs:*",
                                "ecs:*"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "lambda:InvokeFunction",
                                "lambda:ListFunctions"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "opsworks:CreateDeployment",
                                "opsworks:DescribeApps",
                                "opsworks:DescribeCommands",
                                "opsworks:DescribeDeployments",
                                "opsworks:DescribeInstances",
                                "opsworks:DescribeStacks",
                                "opsworks:UpdateApp",
                                "opsworks:UpdateStack"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "cloudformation:CreateStack",
                                "cloudformation:DeleteStack",
                                "cloudformation:DescribeStacks",
                                "cloudformation:UpdateStack",
                                "cloudformation:CreateChangeSet",
                                "cloudformation:DeleteChangeSet",
                                "cloudformation:DescribeChangeSet",
                                "cloudformation:ExecuteChangeSet",
                                "cloudformation:SetStackPolicy",
                                "cloudformation:ValidateTemplate"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Action": [
                                "codebuild:BatchGetBuilds",
                                "codebuild:StartBuild"
                            ],
                            "Resource": "*",
                            "Effect": "Allow"
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "devicefarm:ListProjects",
                                "devicefarm:ListDevicePools",
                                "devicefarm:GetRun",
                                "devicefarm:GetUpload",
                                "devicefarm:CreateUpload",
                                "devicefarm:ScheduleRun"
                            ],
                            "Resource": "*"
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "servicecatalog:ListProvisioningArtifacts",
                                "servicecatalog:CreateProvisioningArtifact",
                                "servicecatalog:DescribeProvisioningArtifact",
                                "servicecatalog:DeleteProvisioningArtifact",
                                "servicecatalog:UpdateProduct"
                            ],
                            "Resource": "*"
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "cloudformation:ValidateTemplate"
                            ],
                            "Resource": "*"
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "ecr:DescribeImages"
                            ],
                            "Resource": "*"
                        }
                    ],
                }
            )],
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "codepipeline.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
        ))

        self.codebuild_role = self._res(ts.iam.Role(
            "CodebuildRole",
            RoleName=ts.Sub(
                "codebuild-Frontend-Build-${Id}-service-role", Id=self.random_id),
            Path="/service-role/",
            Policies=[ts.iam.Policy(
                PolicyName=ts.Sub(
                    "codebuild-Frontend-Build-${Id}-service-role", Id=self.random_id),
                PolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Resource": [
                                ts.Sub(
                                    "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/codebuild/*")
                            ],
                            "Action": [
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents"
                            ]
                        },
                        {
                            "Effect": "Allow",
                            "Resource": [
                                ts.Sub(
                                    "arn:aws:s3:::codepipeline-${AWS::Region}-*")
                            ],
                            "Action": [
                                "s3:PutObject",
                                "s3:GetObject",
                                "s3:GetObjectVersion",
                                "s3:GetBucketAcl",
                                "s3:GetBucketLocation"
                            ]
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "codebuild:CreateReportGroup",
                                "codebuild:CreateReport",
                                "codebuild:UpdateReport",
                                "codebuild:BatchPutTestCases"
                            ],
                            "Resource": [
                                ts.Sub(
                                    "arn:aws:codebuild:${AWS::Region}:${AWS::AccountId}:report-group/*")
                            ]
                        },
                        {
                            "Effect": "Allow",
                            "Action": "ecr:GetAuthorizationToken",
                            "Resource": "*"
                        },
                        {
                            "Effect": "Allow",
                            "Action": "ecr:*",
                            "Resource": ts.Sub("arn:aws:ecr:${AWS::Region}:${AWS::AccountId}:repository/${RepoName}", RepoName=self.param_ecr_repo_name.ref())
                        },
                    ]
                }
            )],
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "codebuild.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
        ))

    def _create_source_stage(self):
        self.source_stage = ts.codepipeline.Stages(
            Name="Source",
            Actions=[
                ts.codepipeline.Actions(
                    Name="Source",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Source",
                        Owner="ThirdParty",
                        Provider="GitHub",
                        Version="1"
                    ),
                    RunOrder=1,
                    Configuration={
                        # TODO: Make these params
                        "Owner": self.param_github_owner.ref(),
                        "Repo": self.param_github_repo.ref(),
                        "Branch": self.param_github_branch.ref(),
                        "OAuthToken": self.param_github_oauth.ref(),
                        "PollForSourceChanges": "false"
                    },
                    OutputArtifacts=[
                        ts.codepipeline.OutputArtifacts(
                            Name="SourceArtifact"
                        )
                    ],
                    InputArtifacts=[],
                    Region=ts.Ref("AWS::Region")
                ),
                ts.codepipeline.Actions(
                    Name="EnvFiles",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Source",
                        Owner="AWS",
                        Provider="S3",
                        Version="1"
                    ),
                    RunOrder=1,
                    Configuration={
                        "S3Bucket": self.param_env_file_bucket.ref(),
                        "S3ObjectKey": self.param_env_file_path.ref(),
                        "PollForSourceChanges": "false"
                    },
                    OutputArtifacts=[
                        ts.codepipeline.OutputArtifacts(
                            Name="EnvFiles"
                        )
                    ],
                    InputArtifacts=[],
                    Region=ts.Ref("AWS::Region")
                )
            ]
        )

    def _create_build_stage(self):
        project_name = ts.Sub("Frontend-Build-${Id}", Id=self.random_id)

        self._res(
            ts.codebuild.Project(
                "FrontendBuild",
                Name=project_name,
                Source=ts.codebuild.Source(
                    Type="CODEPIPELINE",
                    InsecureSsl=False
                ),
                SecondarySourceVersions=[],
                Artifacts=ts.codebuild.Artifacts(
                    Type="CODEPIPELINE",
                    Packaging="NONE",
                    EncryptionDisabled=False
                ),
                Cache=ts.codebuild.ProjectCache(
                    Type="NO_CACHE"
                ),
                Environment=ts.codebuild.Environment(
                    Type="LINUX_CONTAINER",
                    Image="aws/codebuild/standard:3.0",
                    ComputeType="BUILD_GENERAL1_SMALL",
                    EnvironmentVariables=[],
                    PrivilegedMode=True,
                    ImagePullCredentialsType="CODEBUILD"
                ),
                ServiceRole=self.codebuild_role.get_att("Arn"),
                TimeoutInMinutes=60,
                EncryptionKey=ts.Sub("arn:aws:kms:${AWS::Region}:${AWS::AccountId}:alias/aws/s3"),
                BadgeEnabled=False,
                LogsConfig=ts.codebuild.LogsConfig(
                    CloudWatchLogs=ts.codebuild.CloudWatchLogs(
                        Status="ENABLED"
                    ),
                    S3Logs=ts.codebuild.S3Logs(
                        Status="DISABLED",
                        EncryptionDisabled=False
                    )
                )
            )
        )

        self.build_stage = ts.codepipeline.Stages(
            Name="Build",
            Actions=[
                ts.codepipeline.Actions(
                    Name="Build",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Build",
                        Owner="AWS",
                        Provider="CodeBuild",
                        Version="1"
                    ),
                    RunOrder=1,
                    Configuration={
                        "PrimarySource": "SourceArtifact",
                        "ProjectName": project_name,
                        "EnvironmentVariables": ts.Sub(
                            '[{"name":"ECR_REPOSITORY_URI","value":"${ImageRepoName}","type":"PLAINTEXT"},{"name":"STAGING_URL","value":"${StagingUrl}","type":"PLAINTEXT"}]',
                            ImageRepoName=self.param_ecr_repo_name.ref(),
                            StagingUri=self.param_beanstalk_staging_url.ref()
                        )
                    },
                    OutputArtifacts=[
                        ts.codepipeline.OutputArtifacts(
                            Name="BeanstalkDockerrun"
                        )
                    ],
                    InputArtifacts=[
                        ts.codepipeline.InputArtifacts(
                            Name="SourceArtifact"
                        ),
                        ts.codepipeline.InputArtifacts(
                            Name="EnvFiles"
                        )
                    ],
                    Region=ts.Ref("AWS::Region")
                )
            ]
        )

    def _create_approve_stage(self):
        # Create the SNS topic whose subscribers will receive approval messages
        # when a new build is available for deployment.
        sns_topic = self._res(ts.sns.Topic(
            "ApproveFrontendDeployment",
            TopicName="ApproveFrontendDeployment"
        ))

        self.approve_stage = ts.codepipeline.Stages(
            Name="Approve",
            Actions=[
                ts.codepipeline.Actions(
                    Name="DeployStaging",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Deploy",
                        Owner="AWS",
                        Provider="ElasticBeanstalk",
                        Version="1"
                    ),
                    RunOrder=1,
                    Configuration={
                        "ApplicationName": self.param_beanstalk_staging_app.ref(),
                        "EnvironmentName": self.param_beanstalk_staging_env.ref()
                    },
                    OutputArtifacts=[],
                    InputArtifacts=[
                        ts.codepipeline.InputArtifacts(
                            Name="BeanstalkDockerrun"
                        )
                    ],
                    Region=ts.Ref("AWS::Region")
                ),
                ts.codepipeline.Actions(
                    Name="Approve",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Approval",
                        Owner="AWS",
                        Provider="Manual",
                        Version="1"
                    ),
                    RunOrder=2,
                    Configuration={
                        "ExternalEntityLink": self.param_beanstalk_staging_url.ref(),
                        "NotificationArn": sns_topic.ref()
                    },
                    OutputArtifacts=[],
                    InputArtifacts=[],
                    Region=ts.Ref("AWS::Region")
                )
            ]
        )

    def _create_deploy_stage(self):
        self.deploy_stage = ts.codepipeline.Stages(
            Name="Deploy",
            Actions=[
                ts.codepipeline.Actions(
                    Name="Deploy",
                    ActionTypeId=ts.codepipeline.ActionTypeId(
                        Category="Deploy",
                        Owner="AWS",
                        Provider="ElasticBeanstalk",
                        Version="1"
                    ),
                    RunOrder=1,
                    Configuration={
                        "ApplicationName": self.param_beanstalk_prod_app.ref(),
                        "EnvironmentName": self.param_beanstalk_prod_env.ref()
                    },
                    OutputArtifacts=[],
                    InputArtifacts=[
                        ts.codepipeline.InputArtifacts(
                            Name="BeanstalkDockerrun"
                        )
                    ],
                    Region=ts.Ref("AWS::Region")
                )
            ]
        )

    def _create_pipeline(self):
        pipeline_name = ts.Sub("Frontend-${Id}", Id=self.random_id)

        self._res(ts.codepipeline.Pipeline(
            "Frontend",
            Name=pipeline_name,
            # See https://docs.aws.amazon.com/codepipeline/latest/userguide/security-iam.html#how-to-custom-role for role naming
            RoleArn=self.pipeline_role.get_att("Arn"),
            ArtifactStore=ts.codepipeline.ArtifactStore(
                Type="S3",
                Location=self.param_codepipeline_bucket.ref()
            ),
            Stages=[
                self.source_stage,
                self.build_stage,
                self.approve_stage,
                self.deploy_stage
            ]
        ))


def main():
    template_factory = FrontendTemplateFactory()

    template = template_factory.create_template()

    template_yaml = template.to_yaml()

    print(template_yaml)

    with open("frontendpipeline.yml", "w") as output_file:
        output_file.write(template_yaml)


if __name__ == "__main__":
    main()
