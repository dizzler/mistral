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

import re

import jinja2
from jinja2 import parser as jinja_parse
from oslo_log import log as logging
import six

from mistral import exceptions as exc
from mistral.expressions.base_expression import Evaluator
from mistral.utils import expression_utils


LOG = logging.getLogger(__name__)

JINJA_REGEXP = '({{(.*)}})'
JINJA_BLOCK_REGEXP = '({%(.*)%})'

_environment = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True
)

_filters = expression_utils.get_custom_functions()

for name in _filters:
    _environment.filters[name] = _filters[name]


class JinjaEvaluator(Evaluator):
    _env = _environment.overlay()

    @classmethod
    def validate(cls, expression):
        LOG.debug(
            "Validating Jinja expression [expression='%s']",
            expression
        )

        if not isinstance(expression, six.string_types):
            raise exc.JinjaEvaluationException(
                "Unsupported type '%s'." % type(expression)
            )

        try:
            parser = jinja_parse.Parser(cls._env, expression, state='variable')

            parser.parse_expression()
        except jinja2.exceptions.TemplateError as e:
            raise exc.JinjaGrammarException(
                "Syntax error '%s'." % str(e)
            )

    @classmethod
    def evaluate(cls, expression, data_context):
        LOG.debug(
            "Evaluating Jinja expression [expression='%s', context=%s]"
            % (expression, data_context)
        )

        opts = {'undefined_to_none': False}

        ctx = expression_utils.get_jinja_context(data_context)

        try:
            result = cls._env.compile_expression(expression, **opts)(**ctx)

            # For StrictUndefined values, UndefinedError only gets raised when
            # the value is accessed, not when it gets created. The simplest way
            # to access it is to try and cast it to string.
            str(result)
        except Exception as e:
            raise exc.JinjaEvaluationException(
                "Can not evaluate Jinja expression [expression=%s, error=%s"
                ", data=%s]" % (expression, str(e), data_context)
            )

        LOG.debug("Jinja expression result: %s" % result)

        return result

    @classmethod
    def is_expression(cls, s):
        # The class should only be called from within InlineJinjaEvaluator. The
        # return value prevents the class from being accidentally added as
        # Extension
        return False


class InlineJinjaEvaluator(Evaluator):
    # The regular expression for Jinja variables and blocks
    find_expression_pattern = re.compile(JINJA_REGEXP)
    find_block_pattern = re.compile(JINJA_BLOCK_REGEXP)

    _env = _environment.overlay()

    @classmethod
    def validate(cls, expression):
        LOG.debug(
            "Validating Jinja expression [expression='%s']",
            expression
        )

        if not isinstance(expression, six.string_types):
            raise exc.JinjaEvaluationException(
                "Unsupported type '%s'." % type(expression)
            )

        try:
            cls._env.parse(expression)
        except jinja2.exceptions.TemplateError as e:
            raise exc.JinjaGrammarException(
                "Syntax error '%s'." % str(e)
            )

    @classmethod
    def evaluate(cls, expression, data_context):
        LOG.debug(
            "Evaluating Jinja expression [expression='%s', context=%s]"
            % (expression, data_context)
        )

        patterns = cls.find_expression_pattern.findall(expression)

        if patterns[0][0] == expression:
            result = JinjaEvaluator.evaluate(patterns[0][1], data_context)
        else:
            ctx = expression_utils.get_jinja_context(data_context)
            result = cls._env.from_string(expression).render(**ctx)

            LOG.debug("Jinja expression result: %s" % result)

        return result

    @classmethod
    def is_expression(cls, s):
        return (cls.find_expression_pattern.search(s) or
                cls.find_block_pattern.search(s))
