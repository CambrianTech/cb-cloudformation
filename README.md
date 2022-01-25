# Cambrian Cloudformation
Contains scripts that generate AWS Cloudformation templates.

The templates are auto-generated and published to the [Releases page](https://github.com/CambrianTech/cb-cloudformation/releases) when a tag is pushed with a GitHub workflow action.

# Instructions
## Backend
Image processing backend.

**Requires the [SQS branch of cb-imageprocessingservice](https://github.com/CambrianTech/cb-imageprocessingservice/pull/42)**!
1. If buckets don't exist yet, run `scripts/createbuckets.py` to create the necessary S3 buckets (user uploads, image processing models, image processing results).
2. From within `cbcloudformation/` Run `python generate.py backend <output-path>` to create CloudFormation YAML file using troposphere.
3. Go to AWS CloudFormation and create a stack with the created YAML file from step 2. Enter the bucket names created in step 1.

## Frontend Pipeline
Web frontend pipeline for deploying to Elastic Beanstalk environments after pushes to a GitHub repository.
1. From within `cbcloudformation/` Run `python generate.py frontendpipeline <output-path>` to create CloudFormation YAML file using troposphere.
2. Go to AWS CloudFormation and create a stack with the created YAML file from step 2.