console.log('Loading function');

const aws = require('aws-sdk');

const s3 = new aws.S3({ apiVersion: '2006-03-01' });

const bucket = "cb-backend-data"
const filename = "data.json"

exports.handler = async (event) => {
    
    let key = event.unique_id
    if (!key && event.queryStringParameters && event.queryStringParameters.unique_id) {
        key = event.queryStringParameters.unique_id
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
    
    const response = {
        statusCode: 200,
        body: JSON.stringify({unique_id:key, exists:exists}),
    };
    
    return response;
};
