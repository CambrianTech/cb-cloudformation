# Instructions
1. Run `createbuckets.py` to create the necessary S3 buckets (user uploads, image processing models, image processing results).
2. **Requires the [SQS branch of cb-imageprocessingservice](https://github.com/CambrianTech/cb-imageprocessingservice/pull/42)**! Run `backend.py` to create CloudFormation YAML file using troposphere. The output will be in the `templates/` folder.
3. Go to AWS CloudFormation and create a stack with the created YAML file from step 2. Enter the bucket names created in step 1.