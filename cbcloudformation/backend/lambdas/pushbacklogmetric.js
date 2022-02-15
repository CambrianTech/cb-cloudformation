const AWS = require("aws-sdk")

// Set the region 
AWS.config.update({
    region: "us-east-1"
})

// Create the SQS service object
const sqs = new AWS.SQS({
    apiVersion: "2012-11-05"
})

const autoscaling = new AWS.AutoScaling({
    apiVersion: "2011-01-01"
})

const cloudwatch = new AWS.CloudWatch({
    apiVersion: "2010-08-01"
})

// Set params
const sqsParams = {
    QueueUrl: process.env.QUEUE_URL,
    AttributeNames: ["ApproximateNumberOfMessages"],
}

const autoscalingParams = {
    AutoScalingGroupNames: [
        process.env.AUTOSCALINGGROUP_NAME
    ]
}

function getSuccessfulResponse(body) {
    return {
        statusCode: 200,
        headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store"
        },
        body: JSON.stringify(body)
    }
}

exports.handler = async event => {
    const [attrs, autoscalingDesc] = await Promise.all([
        sqs.getQueueAttributes(sqsParams).promise(),
        autoscaling.describeAutoScalingGroups(autoscalingParams).promise(),
    ])

    console.log("SQS Attrs:", attrs)
    console.log("Autoscaling desc:", autoscalingDesc)

    const desiredCapacity = autoscalingDesc.AutoScalingGroups[0].DesiredCapacity
    const backlog = parseInt(attrs.Attributes.ApproximateNumberOfMessages)

    const backlogPerInstance = backlog / Math.max(1, desiredCapacity)

    console.log("Backlog:", backlog)
    console.log("Desired capacity:", desiredCapacity)
    console.log("Backlog per instance:", backlogPerInstance)

    const metricResponse = await cloudwatch.putMetricData({
        Namespace: "ImageProcessingService",
        MetricData: [
            {
                MetricName: "BacklogPerInstance",
                Value: backlogPerInstance,
                Dimensions: [{
                    Name: "ClusterName",
                    Value: process.env.CLUSTER_NAME
                }],
            },
            {
                MetricName: "Backlog",
                Value: backlog,
                Dimensions: [{
                    Name: "ClusterName",
                    Value: process.env.CLUSTER_NAME
                }],
            },
            {
                MetricName: "DesiredCapacity",
                Value: desiredCapacity,
                Dimensions: [{
                    Name: "ClusterName",
                    Value: process.env.CLUSTER_NAME
                }],
            },
        ],
    }).promise()

    console.log("Put metric data", metricResponse)

    response = {
        "success":true
    }

    return getSuccessfulResponse(response)
}

// Env vars examples:
// QUEUE_URL "https://sqs.us-east-1.amazonaws.com/312943975091/cb-backend-sqs-7-ImageProcessingQueue-1FA1YW6E2FAI7.fifo"
// AUTOSCALINGGROUP_NAME "cb-backend-sqs-7-ImageProcessingAutoScalingGroup-O2Z987K6CZYP"
// CLUSTER_NAME "cb-backend-sqs-7-ImageProcessingCluster-s06rNUhXqoIb"