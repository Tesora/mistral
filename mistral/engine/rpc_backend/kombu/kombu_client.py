# Copyright 2015 - Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
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

from six import moves

import kombu
from oslo_log import log as logging

from mistral.engine.rpc_backend import base as rpc_base
from mistral.engine.rpc_backend.kombu import base as kombu_base
from mistral.engine.rpc_backend.kombu import kombu_listener
from mistral import exceptions as exc
from mistral import utils


LOG = logging.getLogger(__name__)


class KombuRPCClient(rpc_base.RPCClient, kombu_base.Base):
    def __init__(self, conf):
        super(KombuRPCClient, self).__init__(conf)

        self._register_mistral_serialization()

        self.exchange = conf.get('exchange', '')
        self.user_id = conf.get('user_id', 'guest')
        self.password = conf.get('password', 'guest')
        self.topic = conf.get('topic', 'mistral')
        self.server_id = conf.get('server_id', '')
        self.host = conf.get('host', 'localhost')
        self.port = conf.get('port', 5672)
        self.virtual_host = conf.get('virtual_host', '/')
        self.durable_queue = conf.get('durable_queues', False)
        self.auto_delete = conf.get('auto_delete', False)
        self._timeout = conf.get('timeout', 60)
        self.conn = self._make_connection(
            self.host,
            self.port,
            self.user_id,
            self.password,
            self.virtual_host
        )

        # Create exchange.
        exchange = self._make_exchange(
            self.exchange,
            durable=self.durable_queue,
            auto_delete=self.auto_delete
        )

        # Create queue.
        self.queue_name = utils.generate_unicode_uuid()
        self.callback_queue = kombu.Queue(
            self.queue_name,
            exchange=exchange,
            routing_key=self.queue_name,
            durable=False,
            exclusive=True,
            auto_delete=True
        )

        self._listener = kombu_listener.KombuRPCListener(
            connection=self.conn,
            callback_queue=self.callback_queue
        )

        self._listener.start()

    def _wait_for_result(self, correlation_id):
        """Waits for the result from the server.

        Waits for the result from the server, checks every second if
        a timeout occurred. If a timeout occurred - the `RpcTimeout` exception
        will be raised.
        """
        try:
            return self._listener.get_result(correlation_id, self._timeout)
        except moves.queue.Empty:
            raise exc.MistralException("RPC Request timeout")

    def _call(self, ctx, method, target, async=False, **kwargs):
        """Performs a remote call for the given method.

        :param ctx: authentication context associated with mistral
        :param method: name of the method that should be executed
        :param kwargs: keyword parameters for the remote-method
        :param target: Server name
        :param async: bool value means whether the request is
            asynchronous or not.
        :return: result of the method or None if async.
        """
        correlation_id = utils.generate_unicode_uuid()

        body = {
            'rpc_ctx': ctx.to_dict(),
            'rpc_method': method,
            'arguments': kwargs,
            'async': async
        }

        LOG.debug("Publish request: {0}".format(body))

        try:
            if not async:
                self._listener.add_listener(correlation_id)

            # Publish request.
            with kombu.producers[self.conn].acquire(block=True) as producer:
                producer.publish(
                    body=body,
                    exchange=self.exchange,
                    routing_key=self.topic,
                    reply_to=self.queue_name,
                    correlation_id=correlation_id,
                    serializer='mistral_serialization',
                    delivery_mode=2
                )

            # Start waiting for response.
            if async:
                return

            result = self._wait_for_result(correlation_id)
            res_type = result[kombu_base.TYPE]
            res_object = result[kombu_base.RESULT]

            if res_type == 'error':
                raise res_object
        finally:
            if not async:
                self._listener.remove_listener(correlation_id)

        return res_object

    def sync_call(self, ctx, method, target=None, **kwargs):
        return self._call(ctx, method, async=False, target=target, **kwargs)

    def async_call(self, ctx, method, target=None, **kwargs):
        return self._call(ctx, method, async=True, target=target, **kwargs)
