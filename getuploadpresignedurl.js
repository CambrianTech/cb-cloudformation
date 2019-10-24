'use strict';

const AWS = require('aws-sdk');

const s3 = new AWS.S3({
    signatureVersion: "v4",
});

const imageNameRegex = /^[a-zA-Z0-9]+$/;
const keyRegex = imageNameRegex;
const signedUrlExpiryTime = 60 * 60; // Expiry time in seconds

const keyLength = 10;
const subKeyLength = 8;

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
        body: JSON.stringify({ error: "Bad request" })
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
    console.log(`Request: ${JSON.stringify(event)}`);

    if (event.queryStringParameters !== null && event.queryStringParameters !== undefined && event.queryStringParameters.imagenames) {
        console.log(`Received imagenames: ${event.queryStringParameters.imagenames}`);

        let uploadUrl = null;
        let key;

        // If the user didn't pass a key, generate a new one and an upload url for its background image
        if (event.queryStringParameters.key) {
            if (!keyRegex.test(event.queryStringParameters.key)) {
                console.log(`Received bad key: ${event.queryStringParameters.key}`);
                return getBadRequestResponse();
            }

            key = event.queryStringParameters.key;
            uploadUrl = `${key}/${imageName}`;
        } else {
            key = makeId(keyLength);
        }

        // Generate a key for the subdirectory
        const subKey = makeId(subKeyLength);

        const imageNames = event.queryStringParameters.imagenames.split(",").map(name => name.trim());
        const subUploadUrls = {};

        // Create signed upload urls for each of the requested images within the sub-directory
        for (const imageName of imageNames) {
            if (!imageNameRegex.test(imageName)) {
                return getBadRequestResponse();
            }

            const url = s3.getSignedUrl("putObject", {
                Bucket: process.env.BUCKET,
                Key: `${key}/${subKey}/${imageName}`,
                Expires: signedUrlExpiryTime,
            });

            subUploadUrls[imageName] = url;
        }

        const response = {
            key: key,
            subKey: subKey,
            subUploadUrls: subUploadUrls,
        };

        if (uploadUrl) {
            response.uploadUrl = uploadUrl;
        }

        return getSuccessfulResponse(response);
    }

    return getBadRequestResponse();
};