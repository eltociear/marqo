# from torch import FloatTensor
# from typing import Any, Dict, List, Optional, Union
import os
import validators
import requests
import numpy as np
from transformers import XCLIPModel, CLIPTokenizer, XCLIPProcessor, XCLIPVisionModel

import torch
from PIL import Image
from marqo.s2_inference.types import *
from marqo.s2_inference.logger import get_logger
import youtube_dl, pafy, cv2
from transformers import XCLIPModel, CLIPTokenizer, XCLIPProcessor, XCLIPVisionModel


logger = get_logger(__name__)


def get_allowed_video_types():
    return set(('.mp4', '.avi', '.wmv'))


# def format_and_load_CLIP_images(images: List[Union[str, ndarray, ImageType]]) -> VideoType:
#     """takes in a list of strings, arrays or urls and either loads and/or converts to PIL
#         for the clip model
#
#     Args:
#         images (List[Union[str, np.ndarray, ImageType]]): list of file locations or arrays (can be mixed)
#
#     Raises:
#         TypeError: _description_
#
#     Returns:
#         List[ImageType]: list of PIL images
#     """
#     if not isinstance(images, list):
#         raise TypeError(f"expected list but received {type(images)}")
#
#     results = []
#     for image in images:
#         results.append(format_and_load_CLIP_image(image))
#
#     return results

def format_and_load_XCLIP_videos(videos: List[Union[str, ndarray, List[ImageType]]]) -> VideoType:
    """takes in a list of strings, arrays or urls and either loads and/or converts to
    #         VideoType: List[PILImage]
    #         for the clip model
    #
    #     Args:
    #         videos (List[Union[str, np.ndarray, List[ImageType]]]): list of file locations, arrays,
    #        or list of PILImages(can be mixed)
    #
    #     Raises:
    #         TypeError: _description_
    #
    #     Returns:
    #         List[List[ImageType]]: List of VideoType(list of PIL images)
    #     """
    if not isinstance(videos, list):
        raise TypeError(f"expected list but received {type(videos)}")

    results = []
    for video in videos:
        results.append(format_and_load_XCLIP_video(video))

    return results




def _load_video_from_path(video: str) -> VideoType:
    """loads an image into PIL from a string path that is
    either local or a url

    Args:
        image (str): _description_

    Raises:
        ValueError: _description_

    Returns:
        ImageType: _description_
    """

    if os.path.isfile(video):
        video = cv2.VideoCapture(video)
    elif validators.url(video):
        urlPafy = pafy.new(video)
        videoplay = urlPafy.getbest(preftype = "any")
        video = cv2.VideoCapture(videoplay.url)
    else:
        raise ValueError(f"input str of {video} is not a local file or a valid url")

    video = convert_to_listofPIL(video)

    return video


def convert_to_listofPIL(video):
    frames = []
    cap = cv2.VideoCapture(video)
    ret = True

    while ret:
        ret, img = cap.read()  # read one frame from the 'capture' object; img is (H, W, C)
        if ret:
            frames.append(Image.fromarray(img, mode="RGB"))
    return frames


def format_and_load_XCLIP_video(video: Union[str, ndarray, List[ImageType]]) -> VideoType:
    """standardizes the input to be a PIL image

    Args:
        image (Union[str, np.ndarray, ImageType]): can be a local file, url or array

    Raises:
        ValueError: _description_
        TypeError: _description_

    Returns:
        ImageType: PIL image
    """
    # check for the input type
    if isinstance(video, str):
        video = _load_video_from_path(video)
    elif isinstance(video, np.ndarray):
        video = list([Image.fromarray(video[i].astype('uint8'), 'RGB') for i in range(len(video))])

    elif isinstance(video, VideoType):
        video = video
    else:
        raise TypeError(f"input of type {type(video)} did not match allowed types of str, np.ndarray, ImageType")

    return video


def _is_video(inputs: Union[str, List[Union[str, VideoType, ndarray]]]) -> bool:
    # some logic to determine if something is an video or not
    # assume the batch is the same type
    # maybe we use something like this https://github.com/ahupp/python-magic

    _allowed = get_allowed_video_types()

    # we assume the batch is this way if a list
    # otherwise apply over each element
    if isinstance(inputs, list):

        if len(inputs) == 0:
            raise TypeError("received empty list, expected at least one element.")

        thing = inputs[0]
    else:
        thing = inputs

    # if it is a string, determine if it is a local file or url
    if isinstance(thing, str):
        name, extension = os.path.splitext(thing.lower())

        # if it has the correct extension, asssume yes
        if extension in _allowed:
            return True

        # if it is a local file without extension, then raise an error
        if os.path.isfile(thing):
            # we could also read the first part of the file and infer
            raise TypeError(
                f"local file [{thing}] extension {extension} does not match allowed file types of {_allowed}")
        else:
            # if it is not a local file and does not have an extension
            # check if url
            if validators.url(thing):
                return True
            else:
                False
                # raise ValueError(f"{thing} cannot be identified as a local file, url or image")

    # if it is an array, then it is an image
    elif isinstance(thing, (VideoType, ndarray)):
        return True
    else:
        raise TypeError(f"expected type Image or str for inputs but received type {type(thing)}")


class XCLIP:
    """
    conveniance class wrapper to make clip work easily for both text and image encoding
    """

    def __init__(self, model_type: str = "microsoft/xclip-base-patch16-ucf-4-shot", device: str = 'cpu', embedding_dim: int = None,
                 truncate: bool = True, **kwargs) -> None:

        self.model_type = model_type
        self.device = device
        self.model = None
        self.tokenizer = None
        self.processor = None
        self.embedding_dimension = embedding_dim
        self.truncate = truncate

    def load(self) -> None:

        # https://github.com/openai/CLIP/issues/30
        self.processor = XCLIPProcessor.from_pretrained(self.model_type)
        self.model = XCLIPModel.from_pretrained(self.model_type)
        self.tokenizer = CLIPTokenizer.from_pretrained(self.model_type)
        self.visionmodel = XCLIPVisionModel.from_pretrained(self.model_type)
        self.num_input_frames = self.visionmodel.config.num_frames
        self.model.eval()

    def _convert_output(self, output):

        if self.device == 'cpu':
            return output.numpy()
        elif self.device.startswith('cuda'):
            return output.cpu().numpy()

    @staticmethod
    def normalize(outputs):
        return outputs.norm(dim=-1, keepdim=True)

    def encode_text(self, sentence: Union[str, List[str]], normalize=True) -> FloatTensor:

        if self.model is None:
            self.load()

        text = self.tokenizer(sentence, truncate=self.truncate).to(self.device)

        with torch.no_grad():
            outputs = self.model.encode_text(text)

        if normalize:
            _shape_before = outputs.shape
            outputs /= self.normalize(outputs)
            assert outputs.shape == _shape_before

        return self._convert_output(outputs)

    def encode_video(self, videos: Union[str, VideoType, ndarray, List[Union[str, ImageType]]],
                     normalize=True) -> FloatTensor:

        if self.model is None:
            self.load()

        # default to batch encoding
        if isinstance(videos, list):
            video_input = format_and_load_XCLIP_videos(videos)
        else:
            video_input = [format_and_load_XCLIP_video(videos)]

        self.video_input_processed = torch.stack([self.processor(_video).to(self.device) for _video in video_input])

        with torch.no_grad():
            outputs = self.model.get_video_features(self.video_input_processed)

        if normalize:
            _shape_before = outputs.shape
            outputs /= self.normalize(outputs)
            assert outputs.shape == _shape_before
        return self._convert_output(outputs)

    def sub_sampling(self, video, frame_sample_rate = 4):
        seg_len = len(video)
        converted_len = int(self.num_input_frames * frame_sample_rate)
        end_idx = np.random.randint(converted_len, seg_len)
        start_idx = end_idx - converted_len
        indices = np.linspace(start_idx, end_idx, num=self.num_input_frames)
        indices = np.clip(indices, start_idx, end_idx - 1).astype(np.int64)
        return [video[i] for i in indices]



    def encode(self, inputs: Union[str, VideoType, List[Union[str, VideoType]]],
               default: str = 'text', normalize=True, **kwargs) -> FloatTensor:

        infer = kwargs.pop('infer', True)

        if infer and _is_video(inputs):
            is_video = True
        else:
            is_video = False
            if default == 'text':
                is_video = False
            elif default == 'image':
                is_video = True
            else:
                raise ValueError(f"expected default='image' or default='text' but received {default}")

        if is_video:
            logger.debug('video')
            return self.encode_image(inputs, normalize=normalize)
        else:
            logger.debug('text')
            return self.encode_text(inputs, normalize=normalize)

