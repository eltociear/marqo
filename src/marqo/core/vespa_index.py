from abc import ABC, abstractmethod
from typing import Dict, Any

from marqo.core.models import MarqoQuery, MarqoIndex
from marqo.core.models.marqo_index import IndexType


class VespaIndex(ABC):
    @classmethod
    @abstractmethod
    def generate_schema(cls, marqo_index: MarqoIndex) -> str:
        pass

    @classmethod
    @abstractmethod
    def to_vespa_document(cls, marqo_document: Dict[str, Any], marqo_index: MarqoIndex) -> Dict[str, Any]:
        pass

    @classmethod
    @abstractmethod
    def to_marqo_document(cls, vespa_document: Dict[str, Any], marqo_index: MarqoIndex) -> Dict[str, Any]:
        pass

    @classmethod
    @abstractmethod
    def to_vespa_query(cls, query: MarqoQuery) -> Dict[str, Any]:
        pass


def for_marqo_index(marqo_index: MarqoIndex):
    if marqo_index.type == IndexType.Structured:
        from marqo.core.structured_vespa_index import StructuredVespaIndex
        return StructuredVespaIndex
    elif marqo_index.type == IndexType.Unstructured:
        from marqo.core.unstructured_vespa_index import UnstructuredVespaIndex
        return UnstructuredVespaIndex
    else:
        raise ValueError(f"No known implementation for index type {marqo_index.type}")