import marqo.core.constants as constants
from marqo.core.exceptions import InvalidDataTypeError, InvalidFieldNameError
from marqo.core.models import MarqoQuery
from marqo.core.models.marqo_index import *
from marqo.core.vespa_index import VespaIndex
from marqo.exceptions import InternalError


class StructuredVespaIndex(VespaIndex):
    _MARQO_TO_VESPA_TYPE_MAP = {
        FieldType.Text: 'string',
        FieldType.Bool: 'bool',
        FieldType.Int: 'int',
        FieldType.Float: 'float',
        FieldType.ArrayText: 'array<string>',
        FieldType.ArrayInt: 'array<int>',
        FieldType.ArrayFloat: 'array<float>',
        FieldType.ImagePointer: 'string'
    }

    _MARQO_TO_PYTHON_TYPE_MAP = {
        FieldType.Text: str,
        FieldType.Bool: bool,
        FieldType.Int: int,
        FieldType.Float: [float, int],
        FieldType.ArrayText: list,
        FieldType.ArrayInt: list,
        FieldType.ArrayFloat: list,
        FieldType.ImagePointer: str
    }

    _DISTANCE_METRIC_MAP = {
        DistanceMetric.Euclidean: 'euclidean',
        DistanceMetric.Angular: 'angular',
        DistanceMetric.DotProduct: 'dotproduct',
        DistanceMetric.PrenormalizedAnguar: 'prenormalized-angular',
        DistanceMetric.Geodegrees: 'geodegrees',
        DistanceMetric.Hamming: 'hamming'
    }

    _INDEX_FIELD_PREFIX = 'marqo__lexical_'
    _FILTER_FIELD_PREFIX = 'marqo__filter_'
    _CHUNKS_FIELD_PREFIX = 'marqo__chunks_'
    _EMBEDDING_FIELD_PREFIX = 'marqo__embeddings_'

    _SCORE_MODIFIERS_FIELD = 'marqo__score_modifiers'

    _BM25_RANK_PROFILE = 'bm25'
    _EMBEDDING_SIMILARITY_RANK_PROFILE = 'embedding_similarity'
    _MODIFIERS_RANK_PROFILE = 'modifiers'

    _RANK_INPUT_QUERY_EMBEDDING = 'query_embedding'
    _RANK_INPUT_MULT_WEIGHTS = 'mult_weights'
    _RANK_INPUT_ADD_WEIGHTS = 'add_weights'

    _ID_FIELD_NAME = 'id'

    _VESPA_DOC_ID = 'id'
    _VESPA_DOC_FIELDS = 'fields'

    @classmethod
    def generate_schema(cls, marqo_index: MarqoIndex) -> str:
        cls._validate_index_type(marqo_index)

        schema = list()

        schema.append(f'schema {marqo_index.name} {{')
        schema.extend(cls._generate_document_section(marqo_index))
        schema.extend(cls._generate_rank_profiles(marqo_index))
        schema.extend(cls._generate_default_fieldset(marqo_index))
        schema.extend(cls._generate_summaries(marqo_index))
        schema.append('}')

        return '\n'.join(schema)

    @classmethod
    def to_vespa_document(cls, marqo_document: Dict[str, Any], marqo_index: MarqoIndex) -> Dict[str, Any]:
        cls._validate_index_type(marqo_index)

        # Ensure index object is caching otherwise this implementation will be computationally expensive
        marqo_index = cls._ensure_cache_enabled(marqo_index)

        vespa_id: Optional[int] = None
        vespa_fields: Dict[str, Any] = dict()

        # ID
        if constants.MARQO_DOC_ID in marqo_document:
            vespa_id = marqo_document[constants.MARQO_DOC_ID]
            vespa_fields[cls._ID_FIELD_NAME] = vespa_id

        # Fields
        for marqo_field in marqo_document:
            if marqo_field == constants.MARQO_DOC_TENSORS or marqo_field == constants.MARQO_DOC_ID:
                continue  # process tensor fields later

            marqo_value = marqo_document[marqo_field]
            cls._verify_marqo_field_name(marqo_field, marqo_index)
            cls._verify_marqo_field_type(marqo_field, marqo_value, marqo_index)

            index_field = marqo_index.field_map[marqo_field]

            if index_field.lexical_field_name:
                vespa_fields[index_field.lexical_field_name] = marqo_value
            if index_field.filter_field_name:
                vespa_fields[index_field.filter_field_name] = marqo_value
            if not index_field.lexical_field_name and not index_field.filter_field_name:
                vespa_fields[index_field.name] = marqo_value

        # Tensors
        if constants.MARQO_DOC_TENSORS in marqo_document:
            for marqo_tensor_field in marqo_document[constants.MARQO_DOC_TENSORS]:
                marqo_tensor_value = marqo_document[constants.MARQO_DOC_TENSORS][marqo_tensor_field]

                cls._verify_marqo_tensor_field_name(marqo_tensor_field, marqo_index)
                cls._verify_marqo_tensor_field(marqo_tensor_field, marqo_tensor_value)

                chunks = marqo_tensor_value[constants.MARQO_DOC_CHUNKS]
                embeddings = marqo_tensor_value[constants.MARQO_DOC_EMBEDDINGS]

                index_tensor_field = marqo_index.tensor_field_map[marqo_tensor_field]

                vespa_fields[index_tensor_field.chunk_field_name] = chunks
                vespa_fields[index_tensor_field.embeddings_field_name] = \
                    {f'{i}': embeddings[i] for i in range(len(embeddings))}

        vespa_doc = {
            cls._VESPA_DOC_FIELDS: vespa_fields
        }

        if vespa_id is not None:
            vespa_doc[cls._VESPA_DOC_ID] = vespa_id

        return vespa_doc

    def to_marqo_document(cls, vespa_document: Dict[str, Any], marqo_index: MarqoIndex) -> Dict[str, Any]:
        pass

    @classmethod
    def to_vespa_query(cls, query: MarqoQuery) -> Dict[str, Any]:
        pass

    @classmethod
    def _verify_marqo_field_name(cls, field_name: str, marqo_index: MarqoIndex):
        field_map = marqo_index.field_map
        if field_name not in marqo_index.field_map:
            raise InvalidFieldNameError(f'Invalid field name {field_name} for index {marqo_index.name}. '
                                        f'Valid field names are {list(field_map.keys())}')

    @classmethod
    def _verify_marqo_tensor_field_name(cls, field_name: str, marqo_index: MarqoIndex):
        tensor_field_map = marqo_index.tensor_field_map
        if field_name not in marqo_index.field_map:
            raise InvalidFieldNameError(f'Invalid tensor field name {field_name} for index {marqo_index.name}. '
                                        f'Valid tensor field names are {list(tensor_field_map.keys())}')

    @classmethod
    def _verify_marqo_tensor_field(cls, field_name: str, field_value: Dict[str, Any]):
        if not set(field_value.keys()) == {constants.MARQO_DOC_CHUNKS, constants.MARQO_DOC_EMBEDDINGS}:
            raise InternalError(f'Invalid tensor field {field_name}. '
                                f'Expected keys {constants.MARQO_DOC_CHUNKS}, {constants.MARQO_DOC_EMBEDDINGS} '
                                f'but found {", ".join(field_value.keys())}')

    @classmethod
    def _verify_marqo_field_type(cls, field_name: str, value: Any, marqo_index: MarqoIndex):
        marqo_type = marqo_index.field_map[field_name].type
        python_type = cls._get_python_type(marqo_type)
        if isinstance(python_type, list) and not any(isinstance(value, t) for t in python_type) or \
                not isinstance(python_type, list) and not isinstance(value, python_type):
            raise InvalidDataTypeError(f'Invalid value {value} for field {field_name} with Marqo type '
                                       f'{marqo_type.name}. Expected a value of type {python_type}, but found '
                                       f'{type(value)}')

    @classmethod
    def _generate_document_section(cls, marqo_index: MarqoIndex) -> List[str]:
        """
        Generate the document (fields) section of the Vespa schema. Update `marqo_index` with Vespa-level field names.
        """
        document: List[str] = list()

        document.append(f'document {marqo_index.name} {{')

        # ID field
        document.append(f'field {cls._ID_FIELD_NAME} type string {{ indexing: summary }}')

        for field in marqo_index.fields:
            if field.type == FieldType.MultimodalCombination:
                # Subfields will store the value of the multimodal combination field and its tensor field will store
                # the chunks and embeddings
                continue

            field_type = cls._get_vespa_type(field.type)

            if FieldFeature.LexicalSearch in field.features:
                field_name = f'{cls._INDEX_FIELD_PREFIX}{field.name}'
                document.append(f'field {field_name} type {field_type} {{')
                document.append(f'indexing: index | summary')
                document.append('index: enable-bm25')
                document.append('}')

                field.lexical_field_name = field_name

            if FieldFeature.Filter in field.features:
                field_name = f'{cls._FILTER_FIELD_PREFIX}{field.name}'
                document.append(f'field {field_name} type {field_type} {{')
                document.append('indexing: attribute | summary')
                document.append('attribute: fast-search')
                document.append('rank: filter')
                document.append('}')

                field.filter_field_name = field_name

            if FieldFeature.LexicalSearch not in field.features and FieldFeature.Filter not in field.features:
                field_name = field.name
                document.append(f'field {field_name} type {field_type} {{')
                document.append('indexing: summary')
                document.append('}')

        # score modifiers
        if marqo_index.score_modifier_fields:
            document.append(f'field {cls._SCORE_MODIFIERS_FIELD} type tensor<float>(p{{}}) {{ indexing: attribute }}')

        # tensor fields
        model_dim = marqo_index.model.get_dimension()
        for field in marqo_index.tensor_fields:
            chunks_field_name = f'{cls._CHUNKS_FIELD_PREFIX}{field.name}'
            embedding_field_name = f'{cls._EMBEDDING_FIELD_PREFIX}{field.name}'
            document.append(f'field {chunks_field_name} type array<string> {{')
            document.append('indexing: attribute | summary')
            document.append('}')
            document.append(f'field {embedding_field_name} type tensor<float>(p{{}}, x[{model_dim}]) {{')
            document.append('indexing: attribute | index | summary')
            document.append(f'attribute {{ distance-metric: {cls._get_distance_metric(marqo_index.distance_metric)} }}')
            document.append('index { hnsw {')
            document.append(f'max-links-per-node: {marqo_index.hnsw_config.m}')
            document.append(f'neighbors-to-explore-at-insert: {marqo_index.hnsw_config.ef_construction}')
            document.append('}}')
            document.append('}')

            field.chunk_field_name = chunks_field_name
            field.embeddings_field_name = embedding_field_name

        document.append('}')

        return document

    @classmethod
    def _generate_summaries(cls, marqo_index: MarqoIndex) -> List[str]:
        summaries: List[str] = list()

        non_vector_summary_fields = []
        vector_summary_fields = []
        for field in marqo_index.fields:
            if field.type == FieldType.MultimodalCombination:
                # Only has a tensor field which will be added in the next loop
                continue

            target_field_name = field.name
            field_type = cls._get_vespa_type(field.type)
            if field.filter_field_name:
                # Filter fields are in-memory attributes so use this even if there's a lexical field
                source_field_name = field.filter_field_name
            elif field.lexical_field_name:
                source_field_name = field.lexical_field_name
            else:
                source_field_name = field.name

            non_vector_summary_fields.append(
                f'summary {target_field_name} type {field_type} {{ source: {source_field_name} }}'
            )

        for field in marqo_index.tensor_fields:
            non_vector_summary_fields.append(
                f'summary {field.chunk_field_name} type array<string> {{ }}'
            )
            vector_summary_fields.append(
                f'summary {field.embeddings_field_name} type tensor<float>(p{{}}, '
                f'x[{marqo_index.model.get_dimension()}]) {{ }}'
            )

        summaries.append('document-summary all-non-vector-summary {')
        summaries.extend(non_vector_summary_fields)
        summaries.append('}')
        summaries.append('document-summary all-vector-summary {')
        summaries.extend(non_vector_summary_fields)
        summaries.extend(vector_summary_fields)
        summaries.append('}')

        return summaries

    @classmethod
    def _generate_default_fieldset(cls, marqo_index: MarqoIndex) -> List[str]:
        fieldsets: List[str] = list()

        fieldset_fields = marqo_index.lexical_fields

        if fieldset_fields:
            fieldsets.append('fieldset default {')
            if fieldset_fields:
                fieldsets.append(f'fields: {", ".join(fieldset_fields)}')
            fieldsets.append('}')

        return fieldsets

    @classmethod
    def _generate_rank_profiles(cls, marqo_index: MarqoIndex) -> List[str]:
        rank_profiles: List[str] = list()

        lexical_fields = marqo_index.lexical_fields
        score_modifier_fields = marqo_index.score_modifier_fields
        tensor_fields = [field.name for field in marqo_index.tensor_fields]
        model_dim = marqo_index.model.get_dimension()

        bm25_expression = ' + '.join([f'bm25({field})' for field in lexical_fields])
        embedding_similarity_expression = ' + '.join([
            f'if (query({field.name}) > 0, closeness(field, {field.embeddings_field_name}), 0)' for field in
            marqo_index.tensor_fields
        ])

        if lexical_fields:
            rank_profiles.append(f'rank-profile {cls._BM25_RANK_PROFILE} inherits default {{ first-phase {{')
            rank_profiles.append(f'expression: {bm25_expression}')
            rank_profiles.append('}}')

        if tensor_fields:
            rank_profiles.append(f'rank-profile {cls._EMBEDDING_SIMILARITY_RANK_PROFILE} inherits default {{')
            rank_profiles.append('inputs {')
            rank_profiles.append(f'query({cls._RANK_INPUT_QUERY_EMBEDDING}) tensor<float>(x[{model_dim}])')
            for field in tensor_fields:
                rank_profiles.append(f'query({field}): 1')

            rank_profiles.append('}')
            rank_profiles.append('first-phase {')
            rank_profiles.append(f'expression: {embedding_similarity_expression}')
            rank_profiles.append('}}')

        if score_modifier_fields:
            expression = f'if (count(query({cls._RANK_INPUT_MULT_WEIGHTS})) == 0, 1, ' \
                         f'reduce(query({cls._RANK_INPUT_MULT_WEIGHTS}) ' \
                         f'* attribute({cls._SCORE_MODIFIERS_FIELD}), prod)) * score ' \
                         f'+ reduce(query({cls._RANK_INPUT_ADD_WEIGHTS}) ' \
                         f'* attribute({cls._SCORE_MODIFIERS_FIELD}), sum)'
            rank_profiles.append(f'rank-profile {cls._MODIFIERS_RANK_PROFILE} inherits default {{')
            rank_profiles.append('inputs {')
            rank_profiles.append(f'query({cls._RANK_INPUT_MULT_WEIGHTS})  tensor<float>(p{{}})')
            rank_profiles.append(f'query({cls._RANK_INPUT_ADD_WEIGHTS})  tensor<float>(p{{}})')
            rank_profiles.append('}')
            rank_profiles.append('function modify(score) {')
            rank_profiles.append(f'expression: {expression}')
            rank_profiles.append('}}')

            if lexical_fields:
                rank_profiles.append(f'rank-profile {cls._BM25_RANK_PROFILE}_{cls._MODIFIERS_RANK_PROFILE} '
                                     f'inherits {cls._MODIFIERS_RANK_PROFILE} {{ first-phase {{')
                rank_profiles.append(f'expression: modify({bm25_expression})')
                rank_profiles.append('}}')

            if tensor_fields:
                rank_profiles.append(
                    f'rank-profile {cls._EMBEDDING_SIMILARITY_RANK_PROFILE}_{cls._MODIFIERS_RANK_PROFILE} '
                    f'inherits {cls._MODIFIERS_RANK_PROFILE} {{ first-phase {{')
                rank_profiles.append(f'expression: modify({embedding_similarity_expression})')
                rank_profiles.append('}}')

        return rank_profiles

    @classmethod
    def _get_vespa_type(cls, marqo_type: FieldType) -> str:
        try:
            return cls._MARQO_TO_VESPA_TYPE_MAP[marqo_type]
        except KeyError:
            raise InternalError(f'Unknown Marqo type: {marqo_type}')

    @classmethod
    def _get_python_type(cls, marqo_type: FieldType) -> type:
        try:
            return cls._MARQO_TO_PYTHON_TYPE_MAP[marqo_type]
        except KeyError:
            raise InternalError(f'Unknown Marqo type: {marqo_type}')

    @classmethod
    def _get_distance_metric(cls, marqo_distance_metric: DistanceMetric) -> str:
        try:
            return cls._DISTANCE_METRIC_MAP[marqo_distance_metric]
        except KeyError:
            raise ValueError(f'Unknown Marqo distance metric: {marqo_distance_metric}')

    @classmethod
    def _validate_index_type(cls, marqo_index: MarqoIndex) -> None:
        if marqo_index.type != IndexType.Structured:
            raise ValueError(f'Vespa index type must be {IndexType.Structured.name}. '
                             f'This module cannot handle index type {marqo_index.type.name}')

    @classmethod
    def _ensure_cache_enabled(cls, marqo_index):
        if not marqo_index.model_enable_cache:
            return marqo_index.copy_with_caching()

        return marqo_index