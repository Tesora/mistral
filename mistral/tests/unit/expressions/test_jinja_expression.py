# Copyright 2016 - Brocade Communications Systems, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import mock

from mistral import exceptions as exc
from mistral.expressions import jinja_expression as expr
from mistral.tests.unit import base
from mistral import utils

DATA = {
    "server": {
        "id": "03ea824a-aa24-4105-9131-66c48ae54acf",
        "name": "cloud-fedora",
        "status": "ACTIVE"
    },
    "status": "OK"
}

SERVERS = {
    "servers": [
        {'name': 'centos'},
        {'name': 'ubuntu'},
        {'name': 'fedora'}
    ]
}


class JinjaEvaluatorTest(base.BaseTest):
    def setUp(self):
        super(JinjaEvaluatorTest, self).setUp()

        self._evaluator = expr.JinjaEvaluator()

    def test_expression_result(self):
        res = self._evaluator.evaluate('_.server', DATA)
        self.assertEqual({
            'id': '03ea824a-aa24-4105-9131-66c48ae54acf',
            'name': 'cloud-fedora',
            'status': 'ACTIVE'
        }, res)

        res = self._evaluator.evaluate('_.server.id', DATA)
        self.assertEqual('03ea824a-aa24-4105-9131-66c48ae54acf', res)

        res = self._evaluator.evaluate("_.server.status == 'ACTIVE'", DATA)
        self.assertTrue(res)

    def test_wrong_expression(self):
        res = self._evaluator.evaluate("_.status == 'Invalid value'", DATA)
        self.assertFalse(res)

        # One thing to note about Jinja is that by default it would not raise
        # an exception on KeyError inside the expression, it will consider
        # value to be None. Same with NameError, it won't return an original
        # expression (which by itself seems confusing). Jinja allows us to
        # change behavior in both cases by switching to StrictUndefined, but
        # either one or the other will surely suffer.

        self.assertRaises(
            exc.JinjaEvaluationException,
            self._evaluator.evaluate,
            '_.wrong_key',
            DATA
        )

        self.assertRaises(
            exc.JinjaEvaluationException,
            self._evaluator.evaluate,
            'invalid_expression_string',
            DATA
        )

    def test_select_result(self):
        res = self._evaluator.evaluate(
            '_.servers|selectattr("name", "equalto", "ubuntu")',
            SERVERS
        )
        item = list(res)[0]
        self.assertEqual({'name': 'ubuntu'}, item)

    def test_function_string(self):
        self.assertEqual('3', self._evaluator.evaluate('_|string', '3'))
        self.assertEqual('3', self._evaluator.evaluate('_|string', 3))

    def test_function_len(self):
        self.assertEqual(3,
                         self._evaluator.evaluate('_|length', 'hey'))
        data = [{'some': 'thing'}]

        self.assertEqual(
            1,
            self._evaluator.evaluate(
                '_|selectattr("some", "equalto", "thing")|list|length',
                data
            )
        )

    def test_validate(self):
        self._evaluator.validate('abc')
        self._evaluator.validate('1')
        self._evaluator.validate('1 + 2')
        self._evaluator.validate('_.a1')
        self._evaluator.validate('_.a1 * _.a2')

    def test_validate_failed(self):
        self.assertRaises(exc.JinjaGrammarException,
                          self._evaluator.validate,
                          '*')

        self.assertRaises(exc.JinjaEvaluationException,
                          self._evaluator.validate,
                          [1, 2, 3])

        self.assertRaises(exc.JinjaEvaluationException,
                          self._evaluator.validate,
                          {'a': 1})

    def test_function_json_pp(self):
        self.assertEqual('"3"', self._evaluator.evaluate('json_pp(_)', '3'))
        self.assertEqual('3', self._evaluator.evaluate('json_pp(_)', 3))
        self.assertEqual(
            '[\n    1,\n    2\n]',
            self._evaluator.evaluate('json_pp(_)', [1, 2])
        )
        self.assertEqual(
            '{\n    "a": "b"\n}',
            self._evaluator.evaluate('json_pp(_)', {'a': 'b'})
        )
        self.assertEqual(
            '"Mistral\nis\nawesome"',
            self._evaluator.evaluate(
                'json_pp(_)', '\n'.join(['Mistral', 'is', 'awesome'])
            )
        )

    def test_filter_json_pp(self):
        self.assertEqual('"3"', self._evaluator.evaluate('_|json_pp', '3'))
        self.assertEqual('3', self._evaluator.evaluate('_|json_pp', 3))
        self.assertEqual(
            '[\n    1,\n    2\n]',
            self._evaluator.evaluate('_|json_pp', [1, 2])
        )
        self.assertEqual(
            '{\n    "a": "b"\n}',
            self._evaluator.evaluate('_|json_pp', {'a': 'b'})
        )
        self.assertEqual(
            '"Mistral\nis\nawesome"',
            self._evaluator.evaluate(
                '_|json_pp', '\n'.join(['Mistral', 'is', 'awesome'])
            )
        )

    def test_function_uuid(self):
        uuid = self._evaluator.evaluate('uuid()', {})

        self.assertTrue(utils.is_valid_uuid(uuid))

    def test_filter_uuid(self):
        uuid = self._evaluator.evaluate('_|uuid', '3')

        self.assertTrue(utils.is_valid_uuid(uuid))

    def test_function_env(self):
        ctx = {'__env': 'some'}
        self.assertEqual(ctx['__env'], self._evaluator.evaluate('env()', ctx))

    def test_filter_env(self):
        ctx = {'__env': 'some'}
        self.assertEqual(ctx['__env'], self._evaluator.evaluate('_|env', ctx))

    @mock.patch('mistral.db.v2.api.get_task_executions')
    @mock.patch('mistral.workflow.data_flow.get_task_execution_result')
    def test_filter_task_without_taskexecution(self, task_execution_result,
                                               task_executions):
        task = mock.MagicMock(return_value={})
        task_executions.return_value = [task]
        ctx = {
            '__task_execution': None,
            '__execution': {
                'id': 'some'
            }
        }

        result = self._evaluator.evaluate('_|task("some")', ctx)

        self.assertEqual({
            'id': task.id,
            'name': task.name,
            'published': task.published,
            'result': task_execution_result(),
            'spec': task.spec,
            'state': task.state,
            'state_info': task.state_info
        }, result)

    @mock.patch('mistral.db.v2.api.get_task_execution')
    @mock.patch('mistral.workflow.data_flow.get_task_execution_result')
    def test_filter_task_with_taskexecution(self, task_execution_result,
                                            task_execution):
        ctx = {
            '__task_execution': {
                'id': 'some',
                'name': 'some'
            }
        }

        result = self._evaluator.evaluate('_|task("some")', ctx)

        self.assertEqual({
            'id': task_execution().id,
            'name': task_execution().name,
            'published': task_execution().published,
            'result': task_execution_result(),
            'spec': task_execution().spec,
            'state': task_execution().state,
            'state_info': task_execution().state_info
        }, result)

    @mock.patch('mistral.db.v2.api.get_task_execution')
    @mock.patch('mistral.workflow.data_flow.get_task_execution_result')
    def test_function_task(self, task_execution_result, task_execution):
        ctx = {
            '__task_execution': {
                'id': 'some',
                'name': 'some'
            }
        }

        result = self._evaluator.evaluate('task("some")', ctx)

        self.assertEqual({
            'id': task_execution().id,
            'name': task_execution().name,
            'published': task_execution().published,
            'result': task_execution_result(),
            'spec': task_execution().spec,
            'state': task_execution().state,
            'state_info': task_execution().state_info
        }, result)

    @mock.patch('mistral.db.v2.api.get_workflow_execution')
    def test_filter_execution(self, workflow_execution):
        wf_ex = mock.MagicMock(return_value={})
        workflow_execution.return_value = wf_ex
        ctx = {
            '__execution': {
                'id': 'some'
            }
        }

        result = self._evaluator.evaluate('_|execution', ctx)

        self.assertEqual({
            'id': wf_ex.id,
            'name': wf_ex.name,
            'spec': wf_ex.spec,
            'input': wf_ex.input,
            'params': wf_ex.params
        }, result)

    @mock.patch('mistral.db.v2.api.get_workflow_execution')
    def test_function_execution(self, workflow_execution):
        wf_ex = mock.MagicMock(return_value={})
        workflow_execution.return_value = wf_ex
        ctx = {
            '__execution': {
                'id': 'some'
            }
        }

        result = self._evaluator.evaluate('execution()', ctx)

        self.assertEqual({
            'id': wf_ex.id,
            'name': wf_ex.name,
            'spec': wf_ex.spec,
            'input': wf_ex.input,
            'params': wf_ex.params
        }, result)


class InlineJinjaEvaluatorTest(base.BaseTest):
    def setUp(self):
        super(InlineJinjaEvaluatorTest, self).setUp()

        self._evaluator = expr.InlineJinjaEvaluator()

    def test_multiple_placeholders(self):
        expr_str = """
            Statistics for tenant "{{ _.project_id }}"

            Number of virtual machines: {{ _.vm_count }}
            Number of active virtual machines: {{ _.active_vm_count }}
            Number of networks: {{ _.net_count }}

            -- Sincerely, Mistral Team.
        """

        result = self._evaluator.evaluate(
            expr_str,
            {
                'project_id': '1-2-3-4',
                'vm_count': 28,
                'active_vm_count': 0,
                'net_count': 1
            }
        )

        expected_result = """
            Statistics for tenant "1-2-3-4"

            Number of virtual machines: 28
            Number of active virtual machines: 0
            Number of networks: 1

            -- Sincerely, Mistral Team.
        """

        self.assertEqual(expected_result, result)

    def test_block_placeholders(self):
        expr_str = """
            Statistics for tenant "{{ _.project_id }}"

            Number of virtual machines: {{ _.vm_count }}
            {% if _.active_vm_count %}
            Number of active virtual machines: {{ _.active_vm_count }}
            {% endif %}
            Number of networks: {{ _.net_count }}

            -- Sincerely, Mistral Team.
        """

        result = self._evaluator.evaluate(
            expr_str,
            {
                'project_id': '1-2-3-4',
                'vm_count': 28,
                'active_vm_count': 0,
                'net_count': 1
            }
        )

        expected_result = """
            Statistics for tenant "1-2-3-4"

            Number of virtual machines: 28
            Number of networks: 1

            -- Sincerely, Mistral Team.
        """

        self.assertEqual(expected_result, result)

    def test_single_value_casting(self):
        self.assertEqual(3, self._evaluator.evaluate('{{ _ }}', 3))
        self.assertEqual('33', self._evaluator.evaluate('{{ _ }}{{ _ }}', 3))

    def test_function_string(self):
        self.assertEqual('3', self._evaluator.evaluate('{{ _|string }}', '3'))
        self.assertEqual('3', self._evaluator.evaluate('{{ _|string }}', 3))

    def test_validate(self):
        self._evaluator.validate('There is no expression.')
        self._evaluator.validate('{{ abc }}')
        self._evaluator.validate('{{ 1 }}')
        self._evaluator.validate('{{ 1 + 2 }}')
        self._evaluator.validate('{{ _.a1 }}')
        self._evaluator.validate('{{ _.a1 * _.a2 }}')
        self._evaluator.validate('{{ _.a1 }} is {{ _.a2 }}')
        self._evaluator.validate('The value is {{ _.a1 }}.')

    def test_validate_failed(self):
        self.assertRaises(exc.JinjaGrammarException,
                          self._evaluator.validate,
                          'The value is {{ * }}.')

        self.assertRaises(exc.JinjaEvaluationException,
                          self._evaluator.validate,
                          [1, 2, 3])

        self.assertRaises(exc.JinjaEvaluationException,
                          self._evaluator.validate,
                          {'a': 1})
