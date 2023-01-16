"""Functions used to fulfill the add_documents endpoint"""
import copy
import functools
import math
import threading
import warnings
from typing import List

import PIL

from marqo.s2_inference.clip_utils import _is_image, load_image_from_path


def threaded_download_images(allocated_docs: List[dict]) -> None:
    """A thread calls this function to download images for its allocated documents

    This should be called only if treat URLs as images is True
    """
    for doc in allocated_docs:
        for field in list(doc):
            if isinstance(doc[field], str) and _is_image(doc[field]):
                try:
                    doc[field] = load_image_from_path(doc[field])
                except PIL.UnidentifiedImageError:
                    continue


def download_images(docs: List[dict], thread_count: int) -> List[dict]:
    """Concurrently downloads images from each doc.

    This should be called only if treat URLs as images is True

    Note: double retrieving of ungettable images:
        Images that can't be found are ignored and not recorded. This assumes that
        a later function will process images again, and again attempt to get these
        ungettable images - at that point will the failure be recorded to be
        returned to the user.

        This decision was made, because the alternative assumes that we'll replace
        the image URL with some other content - like None - that the next function
        needs to be aware of. In other words, starting to define an interface,
        coupling the functions together.
    """

    docs_per_thread = math.ceil(len(docs)/thread_count)
    copied = copy.deepcopy(docs)
    thread_allocated_docs = [copied[i: i + docs_per_thread] for i in range(docs_per_thread)[::docs_per_thread]]
    warnings.warn("thread_allocated_docs" + str(thread_allocated_docs))
    threads = [threading.Thread(target=threaded_download_images, args=(thread_allocated_docs[i], ))
               for i in range(docs_per_thread)]
    for th in threads:
        th.start()

    for th in threads:
        th.join()

    return functools.reduce(lambda x, y: x + y, thread_allocated_docs, [])


