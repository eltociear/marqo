import pprint
import unittest.mock
import requests
from tests.marqo_test import MarqoTestCase
from marqo.tensor_search import add_docs
from marqo.s2_inference.s2_inference import vectorise
from marqo.tensor_search import tensor_search, index_meta_cache, backend
from marqo.errors import IndexNotFoundError, InvalidArgError, BadRequestError


class TestAddDocumentsUseExistingVectors(MarqoTestCase):

    def setUp(self) -> None:
        self.endpoint = self.authorized_url
        self.generic_header = {"Content-type": "application/json"}
        self.index_name_1 = "my-test-index-1"
        try:
            tensor_search.delete_index(config=self.config, index_name=self.index_name_1)
        except IndexNotFoundError as s:
            pass

    def test_use_existing_vectors_non_existing(self):
        """check parity between a doc created with and without use_existing_vetors,
        for a newly created doc.
        """
        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "desc 2": "content 2. blah blah blah"
            }], auto_refresh=True, use_existing_vectors=False)
        regular_doc = tensor_search.get_document_by_id(
            config=self.config, index_name=self.index_name_1,
            document_id="123", show_vectors=True)

        tensor_search.delete_index(config=self.config, index_name=self.index_name_1)

        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "desc 2": "content 2. blah blah blah"
            }], auto_refresh=True, use_existing_vectors=True)
        use_existing_vetors_doc = tensor_search.get_document_by_id(
            config=self.config, index_name=self.index_name_1,
            document_id="123", show_vectors=True)
        self.assertEqual(use_existing_vetors_doc, regular_doc)

    def test_use_existing_vectors_getting_non_tensorised(self):
        """
        During the initial index, one field is set as a non_tensor_field.
        When we insert the doc again, with use_existing_vectors, because the content
        hasn't changed, we use the existing (non-existent) vectors
        """
        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "non-tensor-field": "content 2. blah blah blah"
            }], auto_refresh=True, non_tensor_fields=["non-tensor-field"])
        d1 = tensor_search.get_document_by_id(
            config=self.config, index_name=self.index_name_1,
            document_id="123", show_vectors=True)
        assert len(d1["_tensor_facets"]) == 1
        assert "title 1" in d1["_tensor_facets"][0]

        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "non-tensor-field": "content 2. blah blah blah"
            }], auto_refresh=True, use_existing_vectors=True)
        d2 = tensor_search.get_document_by_id(
            config=self.config, index_name=self.index_name_1,
            document_id="123", show_vectors=True)
        self.assertEqual(d1["_tensor_facets"], d2["_tensor_facets"])

    def test_use_existing_vectors_check_updates(self):
        """ Check to see if the document has been appropriately updated
        """
        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "modded field": "original content",
                "non-tensor-field": "content 2. blah blah blah"
            }], auto_refresh=True, non_tensor_fields=["non-tensor-field"])

        def pass_through_vectorise(*arg, **kwargs):
            """Vectorise will behave as usual, but we will be able to see the call list
            via mock
            """
            return vectorise(*arg, **kwargs)

        mock_vectorise = unittest.mock.MagicMock()
        mock_vectorise.side_effect = pass_through_vectorise
        @unittest.mock.patch("marqo.s2_inference.s2_inference.vectorise", mock_vectorise)
        def run():
            tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
                {
                    "_id": "123",
                    "title 1": "content 1",  # this one should keep the same vectors
                    "my new field": "cat on mat",  # new vectors because it's a new field
                    "modded field": "updated content",  # new vectors because the content is modified
                    "non-tensor-field": "content 2. blah blah blah",  # this would should still have no vectors
                    "2nd-non-tensor-field": "content 2. blah blah blah"  # this one is explicitly being non-tensorised
                }], auto_refresh=True, non_tensor_fields=["2nd-non-tensor-field"], use_existing_vectors=True)
            content_to_be_vectorised = [call_kwargs['content'] for call_args, call_kwargs
                                        in mock_vectorise.call_args_list]
            assert content_to_be_vectorised == [["cat on mat"], ["updated content"]]
            return True
        assert run()

    def test_use_existing_vectors_check_meta_data(self):
        """

        Checks chunk meta data and vectors are as expected

        """
        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "modded field": "original content",
                "non-tensor-field": "content 2. blah blah blah",
                "field_that_will_disappear": "some stuff",  # this gets dropped during the next add docs call,
                "field_to_be_list": "some stuff",
                "fl": 1.51
            }], auto_refresh=True, non_tensor_fields=["non-tensor-field"])

        use_existing_vetor_doc = {
                "title 1": "content 1",  # this one should keep the same vectors
                "my new field": "cat on mat",  # new vectors because it's a new field
                "modded field": "updated content",  # new vectors because the content is modified
                "non-tensor-field": "content 2. blah blah blah",  # this would should still have no vectors
                "2nd-non-tensor-field": "content 2. blah blah blah",  # this one is explicitly being non-tensorised,
                # should end up in meta data:
                "field_to_be_list": ["hi", "there"],
                "new_field_list": ["some new content"],
                "fl": 101.3,
                "new_bool": False
            }
        tensor_search.add_documents(
            config=self.config, index_name=self.index_name_1, docs=[{"_id": "123", **use_existing_vetor_doc}],
            auto_refresh=True, non_tensor_fields=["2nd-non-tensor-field", "field_to_be_list", 'new_field_list'],
            use_existing_vectors=True)

        updated_doc = requests.get(
            url=F"{self.endpoint}/{self.index_name_1}/_doc/123",
            verify=False
        )
        chunks = [chunk for chunk in updated_doc.json()['_source']['__chunks']]
        # each chunk needs its metadata to be the same as the updated document's content
        for ch in chunks:
            ch_meta_data = {k: v for k, v in ch.items() if not k.startswith("__")}
            assert use_existing_vetor_doc == ch_meta_data
        assert len(chunks) == 3

        # check if the vectors/field content is correct
        for vector_field in ["title 1", "my new field", "modded field"]:
            found_vector_field = False
            for ch in chunks:
                if ch["__field_name"] == vector_field:
                    found_vector_field = True
                    assert ch['__field_content'] == use_existing_vetor_doc[vector_field]
                    assert isinstance(ch[f"__vector_{vector_field}"], list)
            assert found_vector_field

    def test_use_existing_vectors_check_meta_data_mappings(self):
        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "_id": "123",
                "title 1": "content 1",
                "modded field": "original content",
                "non-tensor-field": "content 2. blah blah blah",
                "field_that_will_disappear": "some stuff",  # this gets dropped during the next add docs call
                "field_to_be_list": "some stuff",
                "fl": 1.51
            }], auto_refresh=True, non_tensor_fields=["non-tensor-field"])

        use_existing_vetor_doc = {
            "title 1": "content 1",  # this one should keep the same vectors
            "my new field": "cat on mat",  # new vectors because it's a new field
            "modded field": "updated content",  # new vectors because the content is modified
            "non-tensor-field": "content 2. blah blah blah",  # this would should still have no vectors
            "2nd-non-tensor-field": "content 2. blah blah blah",  # this one is explicitly being non-tensorised,
            # should end up in meta data:
            "field_to_be_list": ["hi", "there"],
            "new_field_list": ["some new content"],
            "fl": 101.3,
            "new_bool": False
        }
        tensor_search.add_documents(
            config=self.config, index_name=self.index_name_1, docs=[{"_id": "123", **use_existing_vetor_doc}],
            auto_refresh=True, non_tensor_fields=["2nd-non-tensor-field", "field_to_be_list", 'new_field_list'],
            use_existing_vectors=True)

        tensor_search.index_meta_cache.refresh_index(config=self.config, index_name=self.index_name_1)

        index_info = tensor_search.get_index_info(config=self.config, index_name=self.index_name_1)
        # text or list of texts:
        text_fields = ["title 1", "my new field", "modded field", "non-tensor-field", "2nd-non-tensor-field",
                       "field_to_be_list", "new_field_list", "field_that_will_disappear"]

        for text_field in text_fields:
            assert index_info.properties[text_field]['type'] == 'text'
            assert index_info.properties['__chunks']['properties'][text_field]['type'] == 'keyword'

        for vector_field in ["title 1", "my new field", "modded field"]:
            assert index_info.properties['__chunks']['properties'][f"__vector_{vector_field}"]['type'] == 'knn_vector'

        for field_name, os_type in [('fl', "float"), ('new_bool', "boolean")]:
            assert index_info.properties[field_name]['type'] == os_type
            assert index_info.properties['__chunks']['properties'][field_name]['type'] == os_type

