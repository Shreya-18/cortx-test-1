#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020 Seagate Technology LLC and/or its Affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com.
#
#

"""Python Library to perform bucket operations using boto3 module."""

import logging
from libs.io.s3api.s3_restapi import S3RestApi

LOGGER = logging.getLogger(__name__)


class S3Bucket(S3RestApi):
    """Class for bucket operations."""

    def create_bucket(self, bucket_name: str) -> dict:
        """
        Creating Bucket.

        :param bucket_name: Name of the bucket.
        :return: Response of create bucket.
        """
        response = self.s3_resource.create_bucket(Bucket=bucket_name)
        LOGGER.debug("Response: %s", str(response))

        return response

    def list_bucket(self) -> list:
        """
        Listing all the buckets.

        :return: Response of bucket list.
        """
        response = [bucket.name for bucket in self.s3_resource.buckets.all()]
        LOGGER.debug(response)

        return response

    def head_bucket(self, bucket_name: str) -> dict:
        """
        To determine if a bucket exists and have a permission to access it.

        :param bucket_name: Name of the bucket.
        :return: Response of head bucket.
        """
        response = self.s3_resource.meta.client.head_bucket(Bucket=bucket_name)
        LOGGER.debug(response)

        return response

    def get_bucket_location(self, bucket_name: str) -> dict:
        """
        Getting Bucket Location.

        :param bucket_name: Name of the bucket.
        :return: Response of bucket location.
        """
        LOGGER.debug("BucketName: %s", bucket_name)
        response = self.s3_resource.meta.client.get_bucket_location(Bucket=bucket_name)
        LOGGER.debug(response)

        return response

    def delete_bucket(self, bucket_name: str, force: bool = False) -> dict:
        """
        Deleting the empty bucket or deleting the buckets along with objects stored in it.

        :param bucket_name: Name of the bucket.
        :param force: Value for delete bucket with object or without object.
        :return: Response of delete bucket.
        """
        bucket = self.s3_resource.Bucket(bucket_name)
        if force:
            LOGGER.debug("This might cause data loss as you have opted for bucket deletion with "
                         "objects in it")
            response = bucket.objects.all().delete()
            LOGGER.debug("Objects deleted successfully. response: %s", response)
        response = bucket.delete()
        LOGGER.debug("Bucket '%s' deleted successfully. Response: %s", bucket_name, response)

        return response

    def get_bucket_storage(self, bucket_name: str) -> int:
        """
        Getting consumed storage of the s3 bucket.

        :param bucket_name: Name of the bucket.
        :return: storage consumed by s3 bucket.
        """
        total_size = 0
        bucket = self.s3_resource.Bucket(bucket_name)
        for each_object in bucket.objects.all():
            total_size += each_object.size
        LOGGER.debug("Total storage: %s", total_size)

        return total_size
