from collections import namedtuple
import troposphere as ts
import troposphere.sqs


BackendSqs = namedtuple("BackendSqs", [
    "image_processing_queue",
])


def create_sqs(template: ts.Template) -> BackendSqs:
    image_processing_queue = template.add_resource(ts.sqs.Queue(
        "ImageProcessingQueue",
        FifoQueue=True,
        VisibilityTimeout=300,
        ContentBasedDeduplication=True,
    ))

    return BackendSqs(
        image_processing_queue
    )
