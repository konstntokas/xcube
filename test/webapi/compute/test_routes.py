# The MIT License (MIT)
# Copyright (c) 2023 by the xcube team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
import time

from ..helpers import RoutesTestCase


class ComputeRoutesTest(RoutesTestCase):

    def test_fetch_compute_operations(self):
        ops, status = self.fetch_json('/compute/operations')
        self.assertIsInstance(ops, dict)
        self.assertIsInstance(ops.get("operations"), list)
        self.assertTrue(len(ops.get("operations")) > 0)
        self.assertEqual(200, status)

    def test_fetch_compute_operation(self):
        op, status = self.fetch_json('/compute/operations/spatial_subset')
        self.assertIsInstance(op, dict)
        self.assertIsInstance(op.get("operationId"), str)
        self.assertEqual('spatial_subset', op.get("operationId"))
        self.assertEqual(200, status)

    def test_fetch_job_management(self):
        job, status = self.fetch_json(
            '/compute/jobs',
            method="PUT",
            body={
                "operationId": "spatial_subset",
                "parameters": {
                    "dataset": "demo",
                    "bbox": [1, 51, 4, 52]
                },
                "output": {
                    "datasetId": "demo_subset",
                    "title": "My demo subset"
                }
            }
        )
        self.assert_job_ok(job)
        self.assertEqual(200, status)

        jobs, status = self.fetch_json(f'/compute/jobs')
        self.assertIsInstance(jobs, dict)
        self.assertIsInstance(jobs.get("jobs"), list)
        self.assertEqual(200, status)

        job_id = job.get("jobId")
        while True:
            time.sleep(0.1)
            job, status = self.fetch_json(f'/compute/jobs/{job_id}')
            self.assert_job_ok(job)
            job_status = job["state"]["status"]
            self.assertEqual(200, status)

            if job_status == "started":
                continue

            if job_status == "completed":
                # Success!
                result = job.get("result")
                self.assertIsInstance(result, dict)
                self.assertEqual("demo_subset", result.get("datasetId"))

                # Check we can find the result:
                dataset, status = self.fetch_json('/datasets/demo_subset')
                self.assertIsInstance(dataset, dict)
                self.assertEqual(200, status)
                break

            if job_status != "running":
                # Fails intentionally
                self.assertEqual("running", job_status)
                break


    def assert_job_ok(self, job):
        self.assertIsInstance(job, dict)
        self.assertIsInstance(job.get("jobId"), int)
        self.assertIsInstance(job.get("request"), dict)
        self.assertIsInstance(job.get("state"), dict)
        self.assertIsInstance(job.get("state").get("status"), str)
