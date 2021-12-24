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

"""
F-23B : Data Durability/Integrity test module for Multipart Files.
"""

import os
import os.path
import logging
import secrets
import pytest

from commons.constants import PROD_FAMILY_LC
from commons.constants import PROD_FAMILY_LR
from commons.constants import PROD_TYPE_K8S
from commons.constants import PROD_TYPE_NODE
from commons.helpers.node_helper import Node
from commons.helpers.pods_helper import LogicalNode
from commons.utils import assert_utils
from commons.utils import system_utils
from commons.utils import config_utils
from commons.params import TEST_DATA_FOLDER, DATAGEN_HOME
from config import di_cfg
from config import CMN_CFG
from config import S3_CFG
from config.s3 import S3_BLKBOX_CFG
from commons.constants import MB
from libs.di.di_error_detection_test_lib import DIErrorDetection
from libs.di.fi_adapter import S3FailureInjection
from libs.di import di_lib
from libs.di.di_mgmt_ops import ManagementOPs
from libs.s3 import s3_multipart
from libs.s3 import SECRET_KEY, ACCESS_KEY
from libs.s3.s3_test_lib import S3TestLib
from libs.s3.s3_multipart_test_lib import S3MultipartTestLib
from libs.s3 import cortxcli_test_lib
from libs.s3 import s3_s3cmd
from libs.s3.s3_blackbox_test_lib import MinIOClient


@pytest.fixture(scope="class", autouse=False)
def setup_multipart_fixture(request):
    """
    Yield fixture to setup pre requisites and teardown them.
    Part before yield will be invoked prior to each test case and
    part after yield will be invoked after test call i.e as teardown.
    """
    request.cls.log = logging.getLogger(__name__)
    request.cls.log.info("STARTED: Setup test operations.")
    request.cls.secure_range = secrets.SystemRandom()
    request.cls.s3_test_obj = S3TestLib()
    request.cls.s3_mp_test_obj = S3MultipartTestLib()
    request.cls.hostnames = list()
    request.cls.connections = list()
    request.cls.nodes = CMN_CFG["nodes"]
    if request.cls.cmn_cfg["product_family"] == PROD_FAMILY_LR and \
            request.cls.cmn_cfg["product_type"] == PROD_TYPE_NODE:
        for node in request.cls.nodes:
            node_obj = Node(hostname=node["hostname"],
                            username=node["username"],
                            password=node["password"])
            node_obj.connect()
            request.cls.connections.append(node_obj)
            request.cls.hostnames.append(node["hostname"])
    elif request.cls.cmn_cfg["product_family"] == PROD_FAMILY_LC and \
            request.cls.cmn_cfg["product_type"] == PROD_TYPE_K8S:
        request.cls.log.error("Product family: LC")
        # Add k8s masters
        for node in request.cls.nodes:
            if node["node_type"].lower() == "master":
                node_obj = LogicalNode(hostname=node["hostname"],
                                       username=node["username"],
                                       password=node["password"])
                request.cls.connections.append(node_obj)
                request.cls.hostnames.append(node["hostname"])

    request.cls.account_name = di_lib.get_random_account_name()
    s3_acc_passwd = di_cfg.s3_acc_passwd
    request.cls.s3_account = ManagementOPs.create_s3_user_csm_rest(request.cls.account_name,
                                                                   s3_acc_passwd)
    request.cls.bucket_name = di_lib.get_random_bucket_name()
    # create bucket

    request.cls.acc_del = False
    request.cls.log.info("ENDED: setup test operations.")
    yield
    request.cls.log.info("STARTED: Teardown operations")
    if request.cls.s3_account:
        request.cls.log.debug(f"Deleting the s3 account {request.cls.s3_account}")
        ManagementOPs.delete_s3_user_csm_rest(request.cls.account_name)
    request.cls.log.info("Deleted the s3 accounts and users")
    request.cls.log.info("ENDED: Teardown operations")


@pytest.fixture(scope="function", autouse=False)
def setup_minio(request):
    """Setup minio client for a test."""
    request.cls.log = logging.getLogger(__name__)
    request.cls.log.info("STARTED: Mino Setup started.")
    request.cls.minio = MinIOClient()
    resp = MinIOClient.configre_minio_cloud(minio_repo=S3_CFG["minio_repo"],
                                            endpoint_url=S3_CFG["s3_url"],
                                            s3_cert_path=S3_CFG["s3_cert_path"],
                                            minio_cert_path_list=S3_CFG["minio_crt_path_list"],
                                            access=ACCESS_KEY,
                                            secret=SECRET_KEY)
    assert_utils.assert_true(resp, "failed to setup minio: {}".format(resp))
    resp = system_utils.path_exists(S3_CFG["minio_path"])
    assert_utils.assert_true(resp, "minio config not exists: {}".format(S3_CFG["minio_path"]))
    minio_dict = config_utils.read_content_json(S3_CFG["minio_path"], mode='rb')
    if (ACCESS_KEY != minio_dict["aliases"]["s3"]["accessKey"]
            or SECRET_KEY != minio_dict["aliases"]["s3"]["secretKey"]):
        resp = MinIOClient.configure_minio(ACCESS_KEY, SECRET_KEY)
        assert_utils.assert_true(resp, f'Failed to update keys in {S3_CFG["minio_path"]}')
    request.cls.minio_cnf = S3_BLKBOX_CFG["minio_cfg"]
    request.cls.log.info("ENDED: Min IO Setup ended.")


# pylint: disable=no-member
@pytest.mark.usefixtures("setup_multipart_fixture")
class TestDICheckMultiPart:
    """DI Test suite for F23B Multipart files."""

    def setup_method(self):
        """
        Test method level setup.
        """
        self.edtl = DIErrorDetection()
        self.fi_adapter = S3FailureInjection(cmn_cfg=CMN_CFG)
        self.log = logging.getLogger(__name__)
        self.test_dir_path = os.path.join(
            DATAGEN_HOME, TEST_DATA_FOLDER, "TestDataDurability")
        self.file_path = os.path.join(self.test_dir_path, di_lib.get_random_file_name())
        if not system_utils.path_exists(self.test_dir_path):
            system_utils.make_dirs(self.test_dir_path)
            self.log.info("Created path: %s", self.test_dir_path)

        self.log.info("ENDED: setup test data.")

    def teardown_method(self):
        """
        Test method level teardown.
        """
        self.log.info("STARTED: Teardown of test data")
        self.log.info("Deleting all buckets/objects created during TC execution")
        resp = self.s3_test_obj.bucket_list()
        if self.bucket_name in resp[1]:
            resp = self.s3_test_obj.delete_bucket(self.bucket_name, force=True)
            assert_utils.assert_true(resp[0], resp[1])
        self.log.info("All the buckets/objects deleted successfully")
        self.log.info("Deleting the file created locally for object")
        if system_utils.path_exists(self.file_path):
            self.log.debug("Deleting existing file: %s", str(self.file_path))
            system_utils.remove_file(self.file_path)
            system_utils.remove_dirs(self.test_dir_path)
            self.log.info("Local file was deleted")

        self.log.info("ENDED: Teardown method")

    @pytest.fixture(scope="function", autouse=False)
    def create_testdir_cleanup(self):
        """
        Yield fixture to setup pre requisites and teardown them.
        Part before yield will be invoked prior to each test case and
        part after yield will be invoked after test call i.e as teardown.
        """
        self.test_dir_path = os.path.join(
            DATAGEN_HOME, TEST_DATA_FOLDER, "TestDataDurability")
        self.file_path = os.path.join(self.test_dir_path, di_lib.get_random_file_name())
        if not system_utils.path_exists(self.test_dir_path):
            system_utils.make_dirs(self.test_dir_path)
            self.log.info("Created path: %s", self.test_dir_path)

        self.log.info("ENDED: setup test data.")
        yield
        self.log.info("STARTED: Teardown of test data")
        self.log.info("Deleting the file created locally for object")
        if system_utils.path_exists(self.file_path):
            system_utils.remove_dirs(self.test_dir_path)
        self.log.info("Local file was deleted")
        self.log.info("Deleting all buckets/objects created during TC execution")

        resp = self.s3_test_obj.bucket_list()
        if self.bucket_name in resp[1]:
            resp = self.s3_test_obj.delete_bucket(self.bucket_name, force=True)
            assert_utils.assert_true(resp[0], resp[1])
        self.log.info("All the buckets/objects deleted successfully")
        self.log.info("Deleting the IAM accounts and users")
        self.log.debug(self.s3_account)
        if self.s3_account:
            for acc in self.s3_account:
                self.cli_obj = cortxcli_test_lib.CortxCliTestLib()
                resp = self.cli_obj.login_cortx_cli(
                    username=acc, password=self.s3acc_passwd)
                self.log.debug("Deleting %s account", acc)
                self.cli_obj.delete_all_iam_users()
                self.cli_obj.logout_cortx_cli()
                self.cli_obj.delete_account_cortxcli(
                    account_name=acc, password=self.s3acc_passwd)
                self.log.info("Deleted %s account successfully", acc)
        self.log.info("Deleted the IAM accounts and users")
        self.cli_obj.close_connection()
        self.hobj.disconnect()
        self.log.info("ENDED: Teardown operations")

    # pylint: disable=max-args
    def do_multipart_upload(self, bucket_name, object_name, object_path, file_size, total_parts):
        """Initiate multipart upload, upload parts and complete it.
        Assumes bucket is already created.
        """
        self.log.info("Initiating multipart upload")
        res = self.s3_mp_test_obj.create_multipart_upload(bucket_name, object_name)
        assert_utils.assert_true(res[0], res[1])
        mpu_id = res[1]["UploadId"]
        self.log.info("Multipart Upload initiated with mpu_id %s", mpu_id)
        self.log.info("Uploading parts into bucket")
        res = self.s3_mp_test_obj.upload_parts(mpu_id, bucket_name, object_name, file_size,
                                               total_parts=total_parts,
                                               multipart_obj_path=object_path,
                                               create_file=False)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(len(res[1]), total_parts, res[1])
        parts = res[1]
        self.log.info("Uploaded parts into bucket: %s", parts)
        self.log.info("Listing parts of multipart upload")
        res = self.s3_mp_test_obj.list_parts(mpu_id, bucket_name, object_name)
        assert_utils.assert_true(res[0], res[1])
        self.log.info("Listed parts of multipart upload: %s", res[1])
        self.log.info("Completing multipart upload")
        res = self.s3_mp_test_obj.complete_multipart_upload(mpu_id, parts, bucket_name, object_name)
        assert_utils.assert_true(res[0], res[1])
        res = self.s3_test_obj.object_list(self.bucket_name)
        assert_utils.assert_in(self.object_name, res[1], res[1])
        self.log.info("Multipart upload completed")
        self.log.info("Initiate multipart upload, upload parts,"
                      " list parts and complete multipart upload")
        return mpu_id, parts

    @pytest.mark.skip(reason="Feature is not in place hence marking skip.")
    @pytest.mark.data_integrity
    @pytest.mark.data_durability
    @pytest.mark.tags('TEST-22501')
    def test_verify_data_integrity_with_correct_checksum_22501(self):
        """
        Test to verify object integrity during an upload with correct checksum.
        Specify checksum and checksum algorithm or ETAG during
        PUT(SHA1, MD5 with and without digest, CRC ( check multi-part)).

        Multi part Put
        with data 64 MB file
        provide correct etag during put
        Verify that get does not fail with internal error
        ** Check CRC/checksum passed header. or s3 logs, Motr logs
        Verify checksum at client side
        """
        sz = 512 * MB
        total_parts = 512
        valid, skip_mark = self.edtl.validate_valid_config()
        if not valid or skip_mark:
            pytest.skip()
        self.log.info("STARTED: Verify data integrity check during read with correct checksum.")
        self.log.info("Step 1: Creating a bucket with name : %s", self.bucket_name)
        res = self.s3_test_obj.create_bucket(self.bucket_name)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(res[1], self.bucket_name, res[1])
        self.log.info("Step 1: Created a bucket with name : %s", self.bucket_name)
        self.log.info("Step 2: Put and object with checksum algo or ETAG.")

        self.edtl.create_file(sz, '', self.file_path)
        file_checksum = system_utils.calculate_checksum(self.file_path, binary_bz64=False)[1]
        self.log.info("Step 2: Put an object with md5 checksum.")
        object_name = os.path.split(self.file_path)[-1]
        dwn_pth = os.path.split(self.file_path)[0]
        download_path = os.path.join(dwn_pth, object_name, 'dwn')
        mpu_id, parts = self.do_multipart_upload(self.bucket_name, object_name,
                                                 self.file_path, sz, total_parts)
        mpd = s3_multipart.MultipartUsingBoto()
        kdict = dict(bucket=self.bucket_name, key=object_name, file_path=download_path)
        mpd.multipart_download(kdict)
        download_checksum = system_utils.calculate_checksum(download_path, binary_bz64=False)[1]
        assert_utils.assert_exact_string(file_checksum, download_checksum,
                                         'Checksum mismatch found in downloaded file')
        self.log.info("ENDED TEST-22501: Test to verify object integrity during an "
                      "upload with correct checksum.")

    @pytest.mark.skip(reason="not tested hence marking skip.")
    @pytest.mark.data_integrity
    @pytest.mark.data_durability
    @pytest.mark.tags('TEST-29814')
    def test_29814(self):
        """
        Corrupt data chunk checksum of an multi part object 32 MB to 128 MB (at s3 checksum)
        and verify read (Get).
        """
        sz = 5 * MB
        parts = 5
        self.log.info("Started: Corrupt data chunk checksum of an multi part object 32 MB to 128 "
                      "MB (at s3 checksum) and verify read (Get).")
        valid, skip_mark = self.edtl.validate_valid_config()
        if not valid or skip_mark:
            pytest.skip()
        res = self.s3_test_obj.create_bucket(self.bucket_name)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(res[1], self.bucket_name, res[1])
        self.log.info("Step 1: Created a bucket with name : %s", self.bucket_name)
        self.log.info("Step 2: Put and object with checksum algo or ETAG.")
        # simulating checksum corruption with data corruption
        # to do enabling checksum feature
        self.log.info("Step 1: Create a corrupted file.")
        self.edtl.create_file(sz, first_byte='z', name=self.file_path)
        file_checksum = system_utils.calculate_checksum(self.file_path, binary_bz64=False)[1]
        object_name = os.path.split(self.file_path)[-1]
        self.log.info("Step 1: created a corrupted file %s", self.file_path)
        self.log.info("Step 2: enabling data corruption")
        status = self.fi_adapter.enable_data_block_corruption()
        if status:
            self.log.info("Step 2: enabled data corruption")
        else:
            self.log.info("Step 2: failed to enable data corruption")
            assert False
        self.log.info("Step 3: upload a file using multipart upload")
        res = self.s3_mp_test_obj.create_multipart_upload(self.bucket_name, object_name)
        mpu_id = res[1]["UploadId"]
        self.log.info("Multipart Upload initiated with mpu_id %s", mpu_id)
        parts = list()
        res_sp_file = system_utils.split_file(filename=self.file_path, size=sz, split_count=parts,
                                              random_part_size=False)
        i = 0
        while i < parts:
            with open(res_sp_file[i]["Output"], "rb") as file_pointer:
                data = file_pointer.read()
            resp = self.s3_mp_test_obj.upload_part(body=data,
                                                   bucket_name=self.bucket_name,
                                                   object_name=object_name,
                                                   upload_id=mpu_id, part_number=i + 1)
            parts.append({"PartNumber": i + 1, "ETag": resp[1]["ETag"]})
            i += 1
        self.s3_mp_test_obj.complete_multipart_upload(mpu_id=mpu_id, parts=parts,
                                                      bucket=self.bucket_name,
                                                      object_name=object_name)
        self.log.info("Step 4: verify download object fails with 5xx error code")
        dwn_pth = os.path.split(self.file_path)[0]
        download_path = os.path.join(dwn_pth, object_name, 'dwn')
        mpd = s3_multipart.MultipartUsingBoto()
        kdict = dict(bucket=self.bucket_name, key=object_name, file_path=download_path)
        try:
            mpd.multipart_download(kdict)
        except Exception as fault:
            self.log.error(fault)
        else:
            assert False, 'Download passed'

        download_checksum = system_utils.calculate_checksum(download_path, binary_bz64=False)[1]
        assert_utils.assert_exact_string(file_checksum, download_checksum,
                                         'Checksum mismatch found in downloaded file')
        self.log.info("Ended: Corrupt data chunk checksum of an multi part object 32 MB to 128 "
                      "MB (at s3 checksum) and verify read (Get).")

    @pytest.mark.skip(reason="not tested hence marking skip.")
    @pytest.mark.data_integrity
    @pytest.mark.data_durability
    @pytest.mark.tags('TEST-29815')
    def test_29815(self):
        """
        Corrupt data chunk checksum of an multi part object 32 MB to 128 MB (at s3 checksum)
        and verify read (Get).
        """
        sz = 5 * MB
        parts = 5
        self.log.info("Started: Corrupt data chunk checksum of an multi part object 32 MB to 128 "
                      "MB (at s3 checksum) and verify read (Get).")
        valid, skip_mark = self.edtl.validate_valid_config()
        if not valid or skip_mark:
            pytest.skip()
        res = self.s3_test_obj.create_bucket(self.bucket_name)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(res[1], self.bucket_name, res[1])
        self.log.info("Step 1: Created a bucket with name : %s", self.bucket_name)
        self.log.info("Step 2: Put and object with checksum algo or ETAG.")
        # simulating checksum corruption with data corruption
        # to do enabling checksum feature
        self.log.info("Step 1: Create a corrupted file.")
        self.edtl.create_file(sz, first_byte='z', name=self.file_path)
        file_checksum = system_utils.calculate_checksum(self.file_path, binary_bz64=False)[1]
        object_name = os.path.split(self.file_path)[-1]
        self.log.info("Step 1: created a corrupted file %s", self.file_path)
        self.log.info("Step 2: enabling data corruption")
        status = self.fi_adapter.enable_data_block_corruption()
        if status:
            self.log.info("Step 2: enabled data corruption")
        else:
            self.log.info("Step 2: failed to enable data corruption")
            assert False
        self.log.info("Step 3: upload a file using multipart upload")
        res = self.s3_mp_test_obj.create_multipart_upload(self.bucket_name, object_name)
        mpu_id = res[1]["UploadId"]
        self.log.info("Multipart Upload initiated with mpu_id %s", mpu_id)
        parts = list()
        res_sp_file = system_utils.split_file(filename=self.file_path, size=sz, split_count=parts,
                                              random_part_size=False)
        i = 0
        while i < parts:
            with open(res_sp_file[i]["Output"], "rb") as file_pointer:
                data = file_pointer.read()
            resp = self.s3_mp_test_obj.upload_part(body=data,
                                                   bucket_name=self.bucket_name,
                                                   object_name=object_name,
                                                   upload_id=mpu_id, part_number=i + 1)
            parts.append({"PartNumber": i + 1, "ETag": resp[1]["ETag"]})
            i += 1
        self.s3_mp_test_obj.complete_multipart_upload(mpu_id=mpu_id, parts=parts,
                                                      bucket=self.bucket_name,
                                                      object_name=object_name)
        self.log.info("Step 4: verify download object fails with 5xx error code")
        dwn_pth = os.path.split(self.file_path)[0]
        download_path = os.path.join(dwn_pth, object_name, 'dwn')
        mpd = s3_multipart.MultipartUsingBoto()
        kdict = dict(bucket=self.bucket_name, key=object_name, file_path=download_path)
        try:
            mpd.multipart_download(kdict)
        except Exception as fault:
            self.log.error(fault)
        else:
            assert False, 'Download passed'
        download_checksum = system_utils.calculate_checksum(download_path, binary_bz64=False)[1]
        assert_utils.assert_exact_string(file_checksum, download_checksum,
                                         'Checksum mismatch found in downloaded file')
        self.log.info("Ended: Corrupt data chunk checksum of an multi part object 32 MB to 128 "
                      "MB (at s3 checksum) and verify read (Get).")

    @pytest.mark.skip(reason="not tested hence marking skip.")
    @pytest.mark.data_integrity
    @pytest.mark.data_durability
    @pytest.mark.tags('TEST-33268')
    def test_33268(self):
        """
        S3 Put through S3CMD and Corrupt checksum of an object 256KB to 31 MB (at s3 checksum)
        and verify read (Get).
        SZ >= Data Unit Sz

        """
        size = 5 * MB
        self.log.info("STARTED: S3 Put through S3CMD and Corrupt checksum of an object"
                      "256KB to 31 MB (at s3 checksum) and verify read (Get).")
        valid, skip_mark = self.edtl.validate_valid_config()
        if not valid or skip_mark:
            pytest.skip()
        res = self.s3_test_obj.create_bucket(self.bucket_name)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(res[1], self.bucket_name, res[1])
        self.log.info("Step 1: Created a bucket with name : %s", self.bucket_name)
        self.log.info("Step 2: Put and object with checksum algo or ETAG.")
        # simulating checksum corruption with data corruption
        # to do enabling checksum feature
        self.log.info("Step 1: Create a corrupted file.")
        self.edtl.create_file(size, first_byte='z', name=self.file_path)
        # file_checksum = system_utils.calculate_checksum(self.file_path, binary_bz64=False)[1]
        self.log.info("Step 1: created a file with corrupted flag at location %s", self.file_path)
        self.log.info("Step 2: enabling data corruption")
        status = self.fi_adapter.enable_data_block_corruption()
        if not status:
            self.log.info("Step 2: failed to enable data corruption")
            assert False
        else:
            self.log.info("Step 2: enabled data corruption")
        self.log.info("Step 3: upload a file using s3cmd multipart upload")

        odict = dict(access_key=ACCESS_KEY, secret_key=SECRET_KEY,
                     ssl=True, no_check_certificate=False,
                     host_port=CMN_CFG['host_port'], host_bucket='host-bucket',
                     multipart_chunk_size_mb='15MB')

        s3_s3cmd.S3CmdFacade.upload_object_s3cmd(bucket_name=self.bucket_name,
                                                 file_path=self.file_path, **odict)

        object_uri = 's3://' + self.bucket_name + os.path.split(self.file_path)[-1]
        dodict = dict(access_key=ACCESS_KEY, secret_key=SECRET_KEY,
                      ssl=True, no_check_certificate=False,
                      host_port=CMN_CFG['host_port'], object_uri=object_uri)
        try:
            s3_s3cmd.S3CmdFacade.download_object_s3cmd(bucket_name=self.bucket_name,
                                                       file_path=self.file_path + '.bak', **dodict)
        except Exception as fault:
            self.log.error(fault)
        else:
            assert False, 'Download passed'

    @pytest.mark.skip(reason="not tested hence marking skip.")
    @pytest.mark.data_integrity
    @pytest.mark.data_durability
    @pytest.mark.tags("TEST-29818")
    def test_upload_big_obj_minio_corrupt_cheksum_29818(self, setup_minio):
        """S3 Put through MinIO  and Corrupt checksum of an object 151 MB
         and verify read (Get). ( SZ in range 100 MB -256 MB)."""
        size = 151 * MB
        self.log.info("STARTED: upload object of 151 MB using Minion Client")
        upload_obj_cmd = self.minio_cnf["upload_obj_cmd"].format(self.file_path, self.bucket_name)\
                         + self.minio_obj.validate_cert
        list_obj_cmd = self.minio_cnf["list_obj_cmd"].format(self.bucket_name) \
                       + self.minio_obj.validate_cert

        valid, skip_mark = self.edtl.validate_valid_config()
        if not valid or skip_mark:
            pytest.skip()
        res = self.s3_test_obj.create_bucket(self.bucket_name)
        assert_utils.assert_true(res[0], res[1])
        assert_utils.assert_equal(res[1], self.bucket_name, res[1])
        self.log.info("Step 1: Created a bucket with name : %s", self.bucket_name)
        self.log.info("Step 2: Put and object with checksum algo or ETAG.")
        # simulating checksum corruption with data corruption
        # to do enabling checksum feature
        self.log.info("Step 1: Create a corrupted file.")
        self.edtl.create_file(size, first_byte='z', name=self.file_path)
        # file_checksum = system_utils.calculate_checksum(self.file_path, binary_bz64=False)[1]
        self.log.info("Step 1: created a file with corrupted flag at location %s", self.file_path)
        self.log.info("Step 2: enabling data corruption")
        status = self.fi_adapter.enable_data_block_corruption()
        if not status:
            self.log.info("Step 2: failed to enable data corruption")
            assert False
        else:
            self.log.info("Step 2: enabled data corruption")
        self.log.info("Step 3: upload a file using s3cmd multipart upload")

        self.log.info("Step 3: Uploading an object to a bucket %s", self.bucket_name)
        resp = system_utils.run_local_cmd(upload_obj_cmd)
        assert_utils.assert_true(resp[0], resp[1])
        self.log.info("Step 3: Object is uploaded to a bucket %s", self.bucket_name)
        self.log.info("Step 4: Verifying that object is uploaded to a bucket")
        resp = system_utils.run_local_cmd(list_obj_cmd)
        assert_utils.assert_true(resp[0], resp[1])
        assert_utils.assert_in(os.path.basename(self.file_path), resp[1].split(" ")[-1], resp[1])
        self.log.info("Step 4: Verified that object is uploaded to a bucket")
        self.log.info("Step 4: Download object using Minion Client")