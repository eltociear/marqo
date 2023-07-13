import os
import typing
from timeit import default_timer as timer
from marqo import errors
from marqo.tensor_search import enums, configs, constants
from typing import (
    List, Optional, Union, Callable, Iterable, Sequence, Dict, Tuple
)
from marqo.marqo_logging import logger
import copy
from marqo.tensor_search.enums import EnvVars

def build_tensor_search_filter(
        filter_string: str, simple_properties: dict,
        searchable_attribs: Sequence):
    """Builds a Lucene-DSL filter string for OpenSearch, that combines the user's filter string
    with searchable_attributes

    """
    if searchable_attribs is not None:
        copied_searchable_attribs = copy.deepcopy(searchable_attribs)
        searchable_attribs_filter = build_searchable_attributes_filter(
            searchable_attribs=copied_searchable_attribs)
    else:
        searchable_attribs_filter = ""

    contextualised_user_filter = contextualise_user_filter(
        filter_string=filter_string, simple_properties=simple_properties)

    if contextualised_user_filter and searchable_attribs_filter:
        return f"({searchable_attribs_filter}) AND ({contextualised_user_filter})"
    else:
        return f"{searchable_attribs_filter}{contextualised_user_filter}"


def build_searchable_attributes_filter(searchable_attribs: Sequence) -> str:
    """Constructs the filter used to narrow the search down to specific searchable attributes"""
    if len(searchable_attribs) == 0:
        return ""

    vector_prop_count = len(searchable_attribs)

    # brackets surround field name, in case it contains a space:
    sanitised_attr_name = f"({sanitise_lucene_special_chars(searchable_attribs.pop())})"

    if vector_prop_count == 1:
        return f"{enums.TensorField.chunks}.{enums.TensorField.field_name}:{sanitised_attr_name}"
    else:
        return (
            f"{enums.TensorField.chunks}.{enums.TensorField.field_name}:{sanitised_attr_name}"
            f" OR {build_searchable_attributes_filter(searchable_attribs=searchable_attribs)}")


def sanitise_lucene_special_chars(to_be_sanitised: str) -> str:
    """Santitises Lucene's special chars in a string.

    We shouldn't apply this to the user's filter string, as they can choose to escape
    Lucene's special chars themselves.

    This should be used to sanitise a filter string constructed for users behind the
    scenes (such as for searchable attributes).

    See here for more info:
    https://lucene.apache.org/core/6_0_0/queryparser/org/apache/lucene/queryparser/classic/package-summary.html#Escaping_Special_Characters

    """
    # this prevents us from double-escaping backslashes. This may be unnecessary.
    non_backslash_chars = constants.LUCENE_SPECIAL_CHARS.union(constants.NON_OFFICIAL_LUCENE_SPECIAL_CHARS) - {'\\'}

    to_be_sanitised.replace("\\", "\\\\")

    for char in non_backslash_chars:
        to_be_sanitised = to_be_sanitised.replace(char, f'\\{char}')
    return to_be_sanitised


def contextualise_user_filter(filter_string: Optional[str], simple_properties: typing.Iterable) -> str:
    """adds the chunk prefix to the start of properties found in simple string (filter_string)
    This allows for filtering within chunks.

    Because this is a user-defined filter, if they want to filter on a field names that contain
    special characters, we expect them to escape the special characters themselves.

    In order to search chunks we need to append the chunk prefix to the start of the field name.
    This will only work if they escape the special characters in the field names themselves in
    the exact same way that we do.

    Args:
        filter_string: the user defined filter string
        simple_properties: simple properties of an index (such as text or floats
            and bools)

    Returns:
        a string where the properties are referenced as children of a chunk.
    """
    if filter_string is None:
        return ''
    contextualised_filter = filter_string

    for field in simple_properties:
        escaped_field_name = sanitise_lucene_special_chars(field)
        if escaped_field_name in filter_string:
            # we want to replace only the field name that directly corresponds to the simple property,
            # not any other field names that contain the simple property as a substring.
            if (
                    # this is for the case where the field name is at the start of the filter string
                    filter_string.startswith(escaped_field_name) and

                    # for cases like filter_string:"z_z_z:foo", escaped_field_name=z
                    # where the field name is a substring at the start of the field name
                    # in the filter string.
                    # This prevents us from accidentally generating the filter_string:
                    # "__chunks_.z___chunks_.z___chunks_.z:foo":
                    len(filter_string.split(':')[0]) == len(escaped_field_name)
            ):
                contextualised_filter = contextualised_filter.replace(
                    f'{escaped_field_name}:', f'{enums.TensorField.chunks}.{escaped_field_name}:')
            else:
                # the case where the field name is not at the start of the filter string

                # the case where the field name is after as space
                # e.g.: "field_a:foo AND field_b:bar, escaped_field_name=field_b"
                contextualised_filter = contextualised_filter.replace(
                    f' {escaped_field_name}:', f' {enums.TensorField.chunks}.{escaped_field_name}:')

                # the case where the field name is directly after an opening bracket
                contextualised_filter = contextualised_filter.replace(
                    f'({escaped_field_name}:', f'({enums.TensorField.chunks}.{escaped_field_name}:')

    return contextualised_filter