from typing import Dict, Any, Optional, List, Union, cast

import marqo.core.search.search_filter as search_filter
from marqo.core import constants
from marqo.core.exceptions import (InvalidDataTypeError, InvalidFieldNameError, VespaDocumentParsingError,
                                   InvalidDataRangeError, MarqoDocumentParsingError)
from marqo.core.models import MarqoQuery
from marqo.core.models.hybrid_parameters import RankingMethod, RetrievalMethod
from marqo.core.models.marqo_index import FieldType, FieldFeature, Field, logger, SemiStructuredMarqoIndex
from marqo.core.models.marqo_query import MarqoTensorQuery, MarqoLexicalQuery, MarqoHybridQuery
from marqo.core.semi_structured_vespa_index.semi_structured_document import SemiStructuredVespaDocument
from marqo.core.semi_structured_vespa_index import common
from marqo.core.structured_vespa_index.structured_vespa_index import StructuredVespaIndex
from marqo.core.unstructured_vespa_index.unstructured_vespa_index import UnstructuredVespaIndex
from marqo.core.vespa_index import VespaIndex
from marqo.exceptions import InternalError, InvalidArgumentError
import semver


class SemiStructuredVespaIndex(StructuredVespaIndex, UnstructuredVespaIndex):
    """
    An implementation of VespaIndex for SemiStructured indexes.
    """

    def __init__(self, marqo_index: SemiStructuredMarqoIndex):
        super().__init__(marqo_index)

    def get_marqo_index(self) -> SemiStructuredMarqoIndex:
        if isinstance(self._marqo_index, SemiStructuredMarqoIndex):
            return cast(SemiStructuredMarqoIndex, self._marqo_index)
        else:
            raise TypeError('Wrong type of marqo index')

    def to_vespa_document(self, marqo_document: Dict[str, Any]) -> Dict[str, Any]:
        return (SemiStructuredVespaDocument.from_marqo_document(
            marqo_document, marqo_index=self.get_marqo_index())).to_vespa_document()

    def to_marqo_document(self, vespa_document: Dict[str, Any], return_highlights: bool = False) -> Dict[str, Any]:
        return SemiStructuredVespaDocument.from_vespa_document(
            vespa_document, marqo_index=self.get_marqo_index()).to_marqo_document(
            marqo_index=self.get_marqo_index(), return_highlights=return_highlights)

    def to_vespa_query(self, marqo_query: MarqoQuery) -> Dict[str, Any]:
        # Verify attributes to retrieve, if defined
        if marqo_query.attributes_to_retrieve is not None:
            marqo_query.attributes_to_retrieve.append(common.VESPA_FIELD_ID)
            # add chunk field names for tensor fields
            marqo_query.attributes_to_retrieve.extend(
                [self.get_marqo_index().tensor_field_map[att].chunk_field_name
                 for att in marqo_query.attributes_to_retrieve
                 if att in self.get_marqo_index().tensor_field_map]
            )

        # Hybrid must be checked first since it is a subclass of Tensor and Lexical
        if isinstance(marqo_query, MarqoHybridQuery):
            return StructuredVespaIndex._to_vespa_hybrid_query(self, marqo_query)
        elif isinstance(marqo_query, MarqoTensorQuery):
            return StructuredVespaIndex._to_vespa_tensor_query(self, marqo_query)
        elif isinstance(marqo_query, MarqoLexicalQuery):
            return StructuredVespaIndex._to_vespa_lexical_query(self, marqo_query)

        else:
            raise InternalError(f'Unknown query type {type(marqo_query)}')

    @classmethod
    def _get_filter_term(cls, marqo_query: MarqoQuery) -> Optional[str]:
        return UnstructuredVespaIndex._get_filter_term(marqo_query)