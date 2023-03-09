import threading
from marqo.s2_inference.s2_inference import available_models
from marqo.tensor_search.enums import AvailableModelsKey
from marqo.s2_inference.logger import get_logger
from marqo.s2_inference.types import *
from marqo.s2_inference.errors import ModelCacheManageError
from marqo.tensor_search.utils import read_env_vars_and_defaults
from marqo.tensor_search.configs import EnvVars
import torch
from marqo.s2_inference import constants
from marqo.s2_inference.s2_inference import get_model_size

logger = get_logger(__name__)
class AvailableModels:
    def __init__(self):
        self.lock = threading.Lock()

    def validate_model_into_device(self, model_name, model_properties, device):
        with self.lock():
            '''
               A function to manage the memory usage in devices when we want to load a new model
               Args:
                   model_name: The name of the model to load
                   model_properties: The model properties of the model
                   device: The target device to laod the model
               Returns:
                   True we have enough space for the model
                   Raise an error and return False if we can't find enough space for the model.
               '''
            model_size = get_model_size(model_name, model_properties)
            if self.check_memory_threshold_for_model(device, model_size):
                return True
            else:
                model_cache_key_for_device = [key for key in list(available_models) if key.endswith(device)]
                sorted_key_for_device = sorted(model_cache_key_for_device,
                                               key=lambda x: available_models[x][
                                                   AvailableModelsKey.most_recently_used_time])
                for key in sorted_key_for_device:
                    logger.info(
                        f"Eject model = `{key.split('||')[0]}` with size = `{available_models[key].get('model_size', constants.DEFAULT_MODEL_SIZE)}` from device = `{device}` "
                        f"to save space for model = `{model_name}`.")
                    del available_models[key]
                    if self.check_memory_threshold_for_model(device, model_size):
                        return True

                if self.check_memory_threshold_for_model(device, model_size) is False:
                    raise ModelCacheManageError(
                        f"Marqo CANNOT find enough space to load model = `{model_name}` in device = `{device}`.\n"
                        f"Marqo tried to eject all the models on this device = `{device}` but still can't find enough space. \n"
                        f"Please use a smaller model or increase the memory threshold.")

    def check_memory_threshold_for_model(self, device: str, model_size: Union[float, int]) -> bool:
        '''
        Check the memory usage in the target device and decide whether we can add a new model
        Args:
            device: the target device to check
            model_size: the size of the model to load
        Returns:
            True if we have enough space
            False if we don't have enough space
        '''
        if device.startswith("cuda"):
            torch.cuda.synchronize(device)
            used_memory = torch.cuda.memory_allocated(device) / 1024 ** 3
            threshold = read_env_vars_and_defaults(EnvVars.MARQO_MAX_CUDA_MODEL_MEMORY)
        elif device.startswith("cpu"):
            with self.lock():
                used_memory = sum([available_models[key].get("model_size", constants.DEFAULT_MODEL_SIZE) for key, values in
                                   available_models.items() if key.endswith("cpu")])
                threshold = read_env_vars_and_defaults(EnvVars.MARQO_MAX_CPU_MODEL_MEMORY)
        else:
            raise ModelCacheManageError(
                f"Unable to check the device cache for device=`{device}`. The model loading will proceed"
                f"without device cache check. This might break down Marqo if too many models are loaded.")
        if model_size > threshold:
            raise ModelCacheManageError(
                f"You are trying to load a model with size = `{model_size}` into device = `{device}`, which is larger than the device threshlod = `{threshold}`."
                f"We CANNOT find enough space for the model. Please change the threshold by setting the environment variables.\n"
                f"You can check the detailed information at `https://docs.marqo.ai/0.0.16/Advanced-Usage/configuration/`.")
        return used_memory + model_size < threshold



