'use strict';

const AWS = require('aws-sdk');

const s3 = new AWS.S3({
    signatureVersion: "v4",
});

const imageNameRegex = /^[a-zA-Z0-9]+$/;
const signedUrlExpiryTime = 60 * 60; // Expiry time in seconds

function makeId(length) {
    let result = "";
    const characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const charactersLength = characters.length;

    for (let i = 0; i < length; i++) {
        result += characters.charAt(Math.floor(Math.random() * charactersLength));
    }

    return result;
}

function getBadRequestResponse() {
    return {
        statusCode: 400,
        headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        body: JSON.stringify({ error: "Bad request" }))
    }
}

function getSuccessfulResponse(body) {
    return {
        statusCode: 200,
        headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        body: JSON.stringify(body)
    }
}

exports.handler = async (event) => {
    console.log(`Request: ${JSON.stringify(event)}`)

    if (event.queryStringParameters !== null && event.queryStringParameters !== undefined && event.queryStringParameters.imagenames) {
        console.log(`Received imagenames: ${event.queryStringParameters.imagenames}`);

        const key = makeId(32);

        const imageNames = event.queryStringParameters.imagenames.split(",").map(name => name.trim());
        const uploadUrls = [];

        for (const imageName of imageNames) {
            if (!imageNameRegex.test(imageName)) {
                return getBadRequestResponse();
            }

            const url = s3.getSignedUrl("putObject", {
                Bucket: process.env.BUCKET,
                Key: key + "/" + imageName,
                Expires: signedUrlExpiryTime,
            });

            uploadUrls.push(url);
        }

        return getSuccessfulResponse({
            key: key,
            uploadUrls: uploadUrls,
        });
    }

    return getBadRequestResponse();
};