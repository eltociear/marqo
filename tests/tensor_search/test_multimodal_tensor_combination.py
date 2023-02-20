from marqo.errors import IndexNotFoundError, InvalidArgError
from marqo.tensor_search import tensor_search
from marqo.tensor_search.enums import TensorField, IndexSettingsField, SearchMethod
from tests.marqo_test import MarqoTestCase


class TestMultimodalTensorCombination(MarqoTestCase):

    def setUp(self):
        self.index_name_1 = "my-test-index-1"
        try:
            tensor_search.delete_index(config=self.config, index_name=self.index_name_1)
        except IndexNotFoundError as e:
            pass



    def test_add_documents(self):
        tensor_search.create_vector_index(
                        index_name=self.index_name_1, config=self.config, index_settings={
                        IndexSettingsField.index_defaults: {
                            IndexSettingsField.model: "ViT-B/32",
                            IndexSettingsField.treat_urls_and_pointers_as_images: True,
                            IndexSettingsField.normalize_embeddings:False
                        }
                    })

        tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[
            {
                "Title": "Horse rider",
                "combo_text_image": {
                    "A rider is riding a horse jumping over the barrier." : {
                        "weight" : 0.5,
                                        },
                    "https://raw.githubusercontent.com/marqo-ai/marqo/mainline/examples/ImageSearchGuide/data/image1.jpg": {
                    "weight": 0.5,
                                        },
                },
                "_id": "0"
            },

            {
                "Title": "Horse rider",
                "text_field": "A rider is riding a horse jumping over the barrier.",
                "image_field":"https://raw.githubusercontent.com/marqo-ai/marqo/mainline/examples/ImageSearchGuide/data/image1.jpg",
                "_id": "1"
            },
        ], auto_refresh=True)

        res = tensor_search.search(config=self.config,index_name=self.index_name_1, text ="Image for a rider riding a horse.")
        print(res)

    def test_multimodal_tensor_combination_score(self):

        def get_score(document):
            try:
                tensor_search.delete_index(config=self.config, index_name=self.index_name_1)
            except IndexNotFoundError as e:
                pass

            tensor_search.create_vector_index(
                index_name=self.index_name_1, config=self.config, index_settings={
                    IndexSettingsField.index_defaults: {
                        IndexSettingsField.model: "ViT-B/32",
                        IndexSettingsField.treat_urls_and_pointers_as_images: True,
                        IndexSettingsField.normalize_embeddings: False
                    }
                })

            tensor_search.add_documents(config=self.config, index_name=self.index_name_1, docs=[document], auto_refresh=True)
            self.assertEqual(1, tensor_search.get_stats(config=self.config, index_name=self.index_name_1)["numberOfDocuments"])
            res = tensor_search.search(config=self.config, index_name=self.index_name_1,
                                       text="", result_count=1)
            print(tensor_search.get_stats(config=self.config, index_name=self.index_name_1)["numberOfDocuments"])
            print(res)
            return res["hits"][0]["_score"]

        score_1 = get_score({
                "text_field": "A rider is riding a horse jumping over the barrier.",
                #"image_field": "https://raw.githubusercontent.com/marqo-ai/marqo/mainline/examples/ImageSearchGuide/data/image1.jpg",
            })

        print("----"*20)
        score_2 = get_score({
                #"text_field": "A rider is riding a horse jumping over the barrier.",
                "image_field": "https://raw.githubusercontent.com/marqo-ai/marqo/mainline/examples/ImageSearchGuide/data/image1.jpg",
            })
        print("----" * 20)
        score_3 = get_score({
            "combo_text_image": {
                "A rider is riding a horse jumping over the barrier.": {
                    "weight": 0.5,
                },
                "https://raw.githubusercontent.com/marqo-ai/marqo/mainline/examples/ImageSearchGuide/data/image1.jpg": {
                    "weight": 0.5,
                },
        }
        })

        print(score_1, score_2, score_3)
