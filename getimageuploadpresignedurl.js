'use strict';
console.log('Loading generate presigned URL function');

var AWS = require('aws-sdk');

var s3 = new AWS.S3({
    signatureVersion: 'v4',
});

function makeId(length) {
    var result = '';
    var characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    var charactersLength = characters.length;

    for (var i = 0; i < length; i++) {
        result += characters.charAt(Math.floor(Math.random() * charactersLength));
    }

    return result;
}

exports.handler = (event, context, callback) => {
    const url = s3.getSignedUrl('putObject', {
        Bucket: process.env.BUCKET,
        Key: makeId(32),
        Expires: 1000, //expiry time in sec
    });

    var responseCode = 200;
    console.log("Request: " + JSON.stringify(event));

    if (event.queryStringParameters !== null && event.queryStringParameters !== undefined) {
        if (event.queryStringParameters.httpStatus !== undefined && event.queryStringParameters.httpStatus !== null && event.queryStringParameters.httpStatus !== "") {
            console.log("Received http status: " + event.queryStringParameters.httpStatus);
            responseCode = event.queryStringParameters.httpStatus;
        }
    }

    var responseBody = {
        signed_url: url,
    };
    
    var response = {
        statusCode: responseCode,
        headers: {},
        body: JSON.stringify(responseBody)
    };

    console.log("response: " + JSON.stringify(response))

    callback(null, response);
};