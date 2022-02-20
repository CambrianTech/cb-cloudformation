console.log('Loading function');

const aws = require('aws-sdk');

const s3 = new aws.S3({ apiVersion: '2006-03-01' });

const bucket = "cb-backend-data"
const filename = "data.json"

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

exports.handler = async (event) => {
    
    let key = event.key
    if (!key && event.queryStringParameters && event.queryStringParameters.key) {
        key = event.queryStringParameters.key
    }
    
    let exists = false
    
    if (key) {
        const prefix = `${key}/${filename}`;
    
        const params = {
            Bucket: bucket,
            Key: prefix,
        };
        
        try {
            const { ContentType } = await s3.headObject(params).promise();
            exists = true;
        } catch (err) {
            console.log(err);
            // const message = `Error getting object ${prefix} from bucket ${bucket}. Make sure they exist and your bucket is in the same region as this function.`;
            // console.log(message);
        }
    } else {
        key=null
    }

    return getSuccessfulResponse({key:key, exists:exists});
};
