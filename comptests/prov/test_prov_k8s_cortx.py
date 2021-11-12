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

"""Provisioner Component level test cases for CORTX deployment in k8s environment."""

import logging

import pytest

from commons.helpers.pods_helper import LogicalNode
from commons.utils import assert_utils
from config import CMN_CFG, PROV_CFG
from libs.prov.prov_k8s_cortx_deploy import ProvDeployK8sCortxLib

LOGGER = logging.getLogger(__name__)


class TestProvK8Cortx:

    @classmethod
    def setup_class(cls):
        """Setup class"""
        LOGGER.info("STARTED: Setup Module operations")
        cls.deploy_cfg = PROV_CFG["k8s_cortx_deploy"]
        cls.deploy_lc_obj = ProvDeployK8sCortxLib()
        cls.num_nodes = len(CMN_CFG["nodes"])
        cls.worker_node_list = []
        cls.master_node_list = []
        cls.host_list = []
        for node in range(cls.num_nodes):
            node_obj = LogicalNode(hostname=CMN_CFG["nodes"][node]["hostname"],
                                   username=CMN_CFG["nodes"][node]["username"],
                                   password=CMN_CFG["nodes"][node]["password"])
            if CMN_CFG["nodes"][node]["node_type"].lower() == "master":
                cls.master_node_obj = node_obj
                cls.master_node_list.append(node_obj)
            else:
                cls.worker_node_list.append(node_obj)
        LOGGER.info("Done: Setup operations finished.")

    @pytest.mark.lc
    @pytest.mark.comp_prov
    @pytest.mark.tags("TEST-30239")
    def test_30239(self):
        """
        Verify N-Node Cortx Stack Deployment in K8s environment.
        """
        LOGGER.info("STARTED: N-Node k8s based Cortx Deployment.")
        LOGGER.info("Step 1: Perform k8s Cluster Deployment.")
        resp = self.deploy_lc_obj.deploy_cortx_k8s_cluster(self.master_node_list, self.worker_node_list)
        assert_utils.assert_true(resp[0], resp[1])
        LOGGER.info("Step 1: Cluster Deployment completed.")

        LOGGER.info("Step 2: Check Pods Status.")
        path = self.deploy_cfg["k8s_dir"]
        for node in self.master_node_list:
            resp = self.deploy_lc_obj.validate_cluster_status(node, path)
            assert_utils.assert_true(resp[0])
        LOGGER.info("Step 2: Done.")

        LOGGER.info("Step 3: Check hctl Status.")
        pod_name = self.master_node_obj.get_pod_name()
        assert_utils.assert_true(pod_name[0])
        resp = self.deploy_lc_obj.get_hctl_status(self.master_node_obj, pod_name[1])
        assert_utils.assert_true(resp[0])
        LOGGER.info("Step 3: Done.")
        LOGGER.info("ENDED: Test Case Completed.")