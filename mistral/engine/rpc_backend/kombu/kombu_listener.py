# Copyright (c) 2016 Intel Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import itertools
from kombu.mixins import ConsumerMixin
from six import moves
import threading

from oslo_log import log as logging

from mistral.engine.rpc_backend.kombu import base as kombu_base

LOG = logging.getLogger(__name__)


class KombuRPCListener(ConsumerMixin):

    def __init__(self, connections, callback_queue):
        self._results = {}
        self._connections = itertools.cycle(connections)
        self._callback_queue = callback_queue
        self._thread = None
        self.connection = self._connections.next()

        # TODO(ddeja): Those 2 options should be gathered from config.
        self._sleep_time = 1
        self._max_sleep_time = 512

    def add_listener(self, correlation_id):
        self._results[correlation_id] = moves.queue.Queue()

    def remove_listener(self, correlation_id):
        if correlation_id in self._results:
            del self._results[correlation_id]

    def get_consumers(self, Consumer, channel):
        return [Consumer(
            self._callback_queue,
            callbacks=[self.on_message],
            accept=['pickle', 'json']
        )]

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self.run)
            self._thread.daemon = True
            self._thread.start()

    def on_message(self, response, message):
        """Callback on response.

        This method is automatically called when a response is incoming and
        decides if it is the message we are waiting for - the message with the
        result.

        :param response: the body of the amqp message already deserialized
            by kombu
        :param message: the plain amqp kombu.message with additional
            information
        """
        LOG.debug("Got response: {0}".format(response))

        try:
            message.ack()
        except Exception as e:
            LOG.exception("Failed to acknowledge AMQP message: %s" % e)
        else:
            LOG.debug("AMQP message acknowledged.")

            correlation_id = message.properties['correlation_id']

            queue = self._results.get(correlation_id, None)

            if queue:
                result = {
                    kombu_base.TYPE: 'error'
                    if message.properties.get('type') == 'error'
                    else None,
                    kombu_base.RESULT: response
                }
                queue.put(result)
            else:
                LOG.debug(
                    "Got a response, but seems like no process is waiting for"
                    "it [correlation_id={0}]".format(correlation_id)
                )

    def get_result(self, correlation_id, timeout):
        return self._results[correlation_id].get(block=True, timeout=timeout)

    def on_connection_error(self, exc, interval):
        self.connection = self._connections.next()

        LOG.debug("Broker connection failed: %s" % exc)
        LOG.debug("Sleeping for %s seconds, then retrying connection" %
                  interval
                  )
