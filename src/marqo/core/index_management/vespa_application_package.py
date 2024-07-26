import json
import os
import shutil
import textwrap
from typing import Optional, List

import semver
from datetime import datetime

from pathlib import Path

from marqo.base_model import ImmutableBaseModel
from marqo.core.exceptions import InternalError, OperationConflictError, IndexNotFoundError
from marqo.core.models import MarqoIndex
import marqo.logging
import marqo.vespa.vespa_client
import xml.etree.ElementTree as ET

logger = marqo.logging.get_logger(__name__)


class ServiceXml:
    """
    Represents a Vespa service XML file.
    """
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise InternalError('Could not find file %s' % path)
        self._path = path
        self._tree = ET.parse(path)
        self._root = self._tree.getroot()
        self._documents = self._ensure_only_one('content/documents')

    def save(self) -> None:
        self._tree.write(self._path)

    def _ensure_only_one(self, xml_path: str):
        elements = self._root.findall(xml_path)

        if len(elements) > 1:
            raise InternalError(f'Multiple {xml_path} elements found in services.xml. Only one is allowed')
        if len(elements) == 0:
            raise InternalError(f'No {xml_path} element found in services.xml')

        return elements[0]

    def add_schema(self, name: str) -> None:
        if self._documents.find(f'document[@type="{name}"]'):
            logger.warn(f'Schema {name} already exists in services.xml, nothing to add')
        else:
            new_document = ET.SubElement(self._documents, 'document')
            new_document.set('type', name)
            new_document.set('mode', 'index')

    def remove_schema(self, name: str) -> None:
        docs = self._documents.findall(f'document[@type="{name}"]')
        if not docs:
            logger.warn(f'Schema {name} does not exist in services.xml, nothing to remove')
        else:
            for doc in docs:
                self._documents.remove(doc)

    def config_components(self):
        self._cleanup_container_config()
        self._config_search()
        self._config_index_setting_components()

    def _cleanup_container_config(self):
        """
        Components config needs to be in sync with the components in the jar files. This method cleans up the
        custom components config, so we can always start fresh. This assumes that the container section of the
        services.xml file only has `node` config and empty `document-api` and `search` elements initially. Please
        note that any manual config change in container section will be overwritten.
        """
        container_element = self._ensure_only_one('container')
        for child in container_element.findall('*'):
            if child.tag in ['document-api', 'search']:
                child.clear()
            elif child.tag != 'node':
                container_element.remove(child)

    def _config_search(self):
        search_elements = self._ensure_only_one('container/search')
        chain = ET.SubElement(search_elements, 'chain')
        chain.set('id', 'marqo')
        chain.set('inherits', 'vespa')
        self._add_component(chain, 'searcher', 'ai.marqo.search.HybridSearcher')
        
    def _config_index_setting_components(self):
        container_elements = self._ensure_only_one('container')

        # Add index setting handler
        index_setting_handler = self._add_component(container_elements, 'handler',
                                                    'ai.marqo.index.IndexSettingRequestHandler')
        for binding in ['http://*/index-settings/*', 'http://*/index-settings']:
            binding_element = ET.SubElement(index_setting_handler, 'binding')
            binding_element.text = binding

        # Add index setting component
        index_setting_component = self._add_component(container_elements, 'component',
                                                      'ai.marqo.index.IndexSettings')
        config_element = ET.SubElement(index_setting_component, 'config')
        config_element.set('name', 'ai.marqo.index.index-settings')
        ET.SubElement(config_element, 'indexSettingsFile').text = 'marqo_index_settings.json'
        ET.SubElement(config_element, 'indexSettingsHistoryFile').text = 'marqo_index_settings_history.json'

    @staticmethod
    def _add_component(parent: ET.Element, tag: str, name: str, bundle: str = 'marqo-custom-components'):
        element = ET.SubElement(parent, tag)
        element.set('id', name)
        element.set('bundle', bundle)
        return element


class IndexSettingStore:
    """
    Index settings are now stored in a json file within the application package. Up to 3 historical versions of each
    index setting are stored in another json file. This class handles the creation and management of index settings

    Index settings json file format:
    {
        "index1": {
            "name": "index1",
            "version": 1,
            ...
        }
    }

    Index settings history json file format:
    {
        "index2": [
            {
                "name": "index2",
                "version": 2,
               ...
            },
            {
                "name": "index2",
                "version": 1,
               ...
            }
        ]
    }
    """
    _HISTORY_VERSION_LIMIT = 3

    def __init__(self, index_settings_json: str, index_settings_history_json: str):
        self._index_settings = {key: MarqoIndex.parse_obj(value) for key, value in json.loads(index_settings_json).items()}
        self._index_settings_history = {key: [MarqoIndex.parse_obj(value) for value in history_array]
                                        for key, history_array in json.loads(index_settings_history_json).items()}

    def save_to_files(self, json_file: str, history_json_file: str) -> None:
        with open(json_file, 'w') as f:
            # Pydantic 1.x does not support creating jsonable dict. `json.loads(index.json())` is a workaround
            json.dump({key: json.loads(index.json()) for key, index in self._index_settings.items()}, f)
        with open(history_json_file, 'w') as f:
            json.dump({key: [json.loads(index.json()) for index in history] for
                       key, history in self._index_settings_history.items()}, f)

    def save_index_setting(self, index_setting: MarqoIndex) -> None:
        target_version = (index_setting.version or 0) + 1
        name = index_setting.name

        if name in self._index_settings:
            current_version = self._index_settings[name].version
            if current_version + 1 != target_version:
                raise OperationConflictError(f'Conflict in version detected while saving index {name}. '
                                             f'Current version {current_version}, new version {target_version}.')
            self._move_to_history(name)
        else:
            if target_version != 1:
                raise OperationConflictError(f'Conflict in version detected while saving index {name}. '
                                             f'The index does not exist or has been deleted, and we are trying to '
                                             f'upgrade it to version {target_version}')
            # If the name exists in history, it means index with the same name was deleted. Clean the history
            if name in self._index_settings_history:
                del self._index_settings_history[name]

        self._index_settings[name] = index_setting.copy(deep=True, update={'version': target_version})

    def delete_index_setting(self, index_setting_name: str) -> None:
        if index_setting_name not in self._index_settings:
            logger.warn(f"Index setting {index_setting_name} does not exist, nothing to delete")
        else:
            self._move_to_history(index_setting_name)
            del self._index_settings[index_setting_name]

    def get_index(self, index_setting_name: str) -> MarqoIndex:
        return self._index_settings[index_setting_name] if index_setting_name in self._index_settings else None

    def _move_to_history(self, index_setting_name):
        if index_setting_name in self._index_settings_history:
            self._index_settings_history[index_setting_name].insert(0, self._index_settings[index_setting_name])
            self._index_settings_history[index_setting_name] = self._index_settings_history[index_setting_name][
                                                               :self._HISTORY_VERSION_LIMIT]
        else:
            self._index_settings_history[index_setting_name] = [self._index_settings[index_setting_name]]


class MarqoConfig(ImmutableBaseModel):
    version: str

    class Config(ImmutableBaseModel.Config):
        extra = "allow"


class MarqoConfigStore:
    """
    Store Marqo configuration in a JSON file in the application package
    Index settings json file format:
    {
        "version": "2.11.0"
        ...
    }
    """
    def __init__(self, marqo_config_json: str) -> None:
        self._config = MarqoConfig.parse_obj(json.loads(marqo_config_json)) if marqo_config_json else None

    def get(self) -> MarqoConfig:
        return self._config

    def update_version(self, version: str) -> None:
        self._config = MarqoConfig(version=version)

    def save_to_file(self, path: str) -> None:
        if self._config is None:
            raise InternalError(f"Cannot save Marqo config to {path}, it is not set")
        with open(path, "w") as f:
            f.write(self._config.json())


class VespaApplicationPackage:
    """
    Represents a Vespa application package. Downloads the application package from Vespa when initialised.
    Provides convenient methods to manage various configs to the application package.
    """

    def __init__(self, app_root_path: str):
        self.app_root_path = app_root_path
        self.is_configured = os.path.exists(self._full_path('marqo_config.json'))
        self._service_xml = ServiceXml(self._full_path('services.xml'))
        self._marqo_config_store = MarqoConfigStore(self._load_json_from_file('marqo_config.json'))
        self._index_setting_store = IndexSettingStore(
            self._load_json_from_file('marqo_index_settings.json', default_value='{}'),
            self._load_json_from_file('marqo_index_settings_history.json', default_value='{}'))

    def _full_path(self, *paths: str) -> str:
        return os.path.join(self.app_root_path, *paths)

    def _load_json_from_file(self, path: str, default_value: Optional[str] = None) -> str:
        full_path = self._full_path(path)
        if not os.path.exists(full_path):
            return default_value
        with open(full_path, 'r') as file:
            return file.read()

    def get_marqo_config(self) -> MarqoConfig:
        return self._marqo_config_store.get()

    def save_to_disk(self) -> None:
        self._service_xml.save()
        self._marqo_config_store.save_to_file(self._full_path('marqo_config.json'))
        self._index_setting_store.save_to_files(self._full_path('marqo_index_settings.json'),
                                                self._full_path('marqo_index_settings_history.json'))

    def need_bootstrapping(self, marqo_version: str, marqo_config_doc: Optional[MarqoConfig] = None,
                           allow_downgrade: bool = False) -> bool:
        """
        Bootstrapping is needed when
        - the version of Marqo is higher than the version of the deployed application
        - the version of Marqo is lower but allow downgrade is enabled (used for rollback)
        The version of the application is retrieved in the following order:
        - from the 'marqo_config.json' file (Post v2.12.0)
        - from the marqo_config_doc passed in which is marqo__config doc saved in marqo__settings schema (Post v2.1.0)
        - if neither is available, return 2.0.0 as default (Pre v2.1.0 or not bootstrapped yet)
        """
        if self.is_configured and self._marqo_config_store.get():
            app_version = self._marqo_config_store.get().version
        elif marqo_config_doc:
            app_version = marqo_config_doc.version
        else:
            app_version = '2.0.0'

        marqo_sem_version = semver.VersionInfo.parse(marqo_version, optional_minor_and_patch=True)
        app_sem_version = semver.VersionInfo.parse(app_version, optional_minor_and_patch=True)

        return (app_sem_version < marqo_sem_version) or (app_sem_version > marqo_sem_version and allow_downgrade)

    def bootstrap(self, marqo_version: str, existing_index_settings: List[MarqoIndex] = ()) -> None:
        if not self.is_configured and existing_index_settings:
            for index in existing_index_settings:
                self._index_setting_store.save_index_setting(index)

        self._add_default_query_profile()
        self._copy_components_jar()
        self._service_xml.config_components()
        self._marqo_config_store.update_version(marqo_version)

    def _add_default_query_profile(self) -> None:
        content = textwrap.dedent(
            '''
            <query-profile id="default">
                <field name="maxHits">1000</field>
                <field name="maxOffset">10000</field>
            </query-profile>
            '''
        )
        self._save_txt_file(content, 'search/query-profiles', 'default.xml')

    def _copy_components_jar(self) -> None:
        vespa_jar_folder = Path(__file__).parent / '../../../../vespa/target'
        components_jar_files = ['marqo-custom-components-deploy.jar']

        # delete the whole components folder
        components_path = self._full_path('components')
        if os.path.exists(components_path):
            shutil.rmtree(components_path)
        os.makedirs(components_path)

        # copy the components jar file to the empty folder
        for file in components_jar_files:
            shutil.copy(vespa_jar_folder/file, self._full_path('components', file))

    def add_index_setting_and_schema(self, index_setting: MarqoIndex, schema: str) -> None:
        self._index_setting_store.save_index_setting(index_setting)
        self._save_txt_file(schema, 'schemas', f'{index_setting.schema_name}.sd')
        self._service_xml.add_schema(index_setting.schema_name)

    def delete_index_setting_and_schema(self, index_name: str) -> None:
        index = self._index_setting_store.get_index(index_name)
        if index is None:
            raise IndexNotFoundError(f"Index {index_name} not found")

        self._index_setting_store.delete_index_setting(index.name)
        self._delete_file('schemas', f'{index.schema_name}.sd')
        self._service_xml.remove_schema(index.schema_name)
        self._add_schema_removal_override()

    def has_schema(self, name: str) -> bool:
        return os.path.exists(self._full_path('schemas', f'{name}.sd'))

    def has_index(self, name: str) -> bool:
        return self._index_setting_store.get_index(name) is not None

    def _add_schema_removal_override(self) -> None:
        # FIXME we should set a time only a few min in the future to allow minimum window for schema deletion
        content = textwrap.dedent(
            f'''
            <validation-overrides>
                 <allow until='{datetime.utcnow().strftime('%Y-%m-%d')}'>schema-removal</allow>
            </validation-overrides>
            '''
        ).strip()
        self._save_txt_file(content, 'validation-overrides.xml')

    def _save_txt_file(self, content: str, *paths: str) -> None:
        path = self._full_path(*paths)
        if os.path.exists(path):
            logger.warn(f"{path} already exists in application package, overwriting")
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, 'w') as f:
            f.write(content)

    def _delete_file(self, *paths: str) -> None:
        path = self._full_path(*paths)
        if not os.path.exists(path):
            logger.warn(f"{path} does not exist in application package, nothing to delete")
        else:
            os.remove(path)
