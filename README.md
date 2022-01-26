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
4. Create a domain mapping for the created RestApi resource of the created stack:
    - In API Gateway, go to Custom domain names
    - Click on a domain name
    - Click API mappings
    - Configure API mappings
    - Add new mapping
    - Select the created API and click Save
    - The backend is now reachable under that domain (ie. `domain.tld/GetUserUploadPresignedUrl` and `domain.tld/ImageProcessing/segment/{key}`)

## Frontend Pipeline
Web frontend pipeline for deploying to Elastic Beanstalk environments after pushes to a GitHub repository.
1. From within `cbcloudformation/` Run `python generate.py frontendpipeline <output-path>` to create CloudFormation YAML file using troposphere.
2. Go to AWS CloudFormation and create a stack with the created YAML file from step 2.

# Architecture
## Backend
### User point of view / flow
- User requests presigned urls for uploading to an S3 bucket and associated key from API Gateway's `/GetUserUploadPresignedUrl` endpoint
- User uploads room image to the presigned url
- User uses API Gateway's `/ImageProcessing/segment/{key}` to request processing of the image, which immediately returns the result urls
- User polls the result urls until they have a result or a timeout is reached
### Server image processing
- When `/ImageProcessing/segment/{key}` is called, a request is added to an SQS queue to process the key
- Image processing tasks on ECS running the [cb-imageprocessingservice](https://github.com/cambrianTech/cb-imageprocessingservice) image take items out of the queue one at a time, process them and upload the results to S3 which the user is polling
### Server task / instance autoscaling
- The number of tasks is autoscaled up when a custom metric exceeds a threshold or is under a threshold
- Instances are automatically scaled based on the number of tasks using a [Capacity Provider](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cluster-capacity-providers.html) 
- The metric is number of items in the queue per instance in the autoscaling group
- The metric is calculated by a Lambda that runs once a minute and pushed to CloudWatch
- Example: 3 instances and tasks are running, 7 requests come in and get added to the SQS queue, 3 get immediately taken out of the queue and start processing, 4 wait in the queue, the metric will be `4 / 3 = 1.33`
### Server task placement
- A task has containers using the cb-imageprocessingservice and planes images from the [cb-imageprocessingservice](https://github.com/cambrianTech/cb-imageprocessingservice) repository
- The two containers share the same GPU which requires a custom AMI (see [here](https://github.com/aws/containers-roadmap/issues/327#issuecomment-471162879))
- Only one of the containers specifies a GPU requirement, so only one task is placed per instance (assuming the instance type has 1 GPU)