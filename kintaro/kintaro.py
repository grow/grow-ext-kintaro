"""Kintaro extension for integrating Kintaro into Grow sites."""

import datetime
import json
import logging
import os
import re
import grow
import httplib2
from googleapiclient import discovery
from googleapiclient import errors
from grow.common import oauth
from grow.common import utils
from grow.pods import documents
from jinja2.ext import Extension
from protorpc import messages


KINTARO_HOST = 'kintaro-content-server.appspot.com'
KINTARO_API_ROOT = 'https://{host}/_ah/api'.format(host=KINTARO_HOST)
DISCOVERY_URL = (
    KINTARO_API_ROOT + '/discovery/v1/apis/{api}/{apiVersion}/rest')
KINTARO_EDIT_PATH_FORMAT = (
    'https://{host}'
    '/app#/project/{project}'
    '/repo/{repo}'
    '/collection/{collection}'
    '/document/{document}/edit')
PARTIAL_CONVERSION = re.compile(r'([A-Z])')
STORAGE_KEY = 'Grow SDK - Kintaro'

# Silence extra logging from googleapiclient.
discovery.logger.setLevel(logging.WARNING)


OAUTH_SCOPES = ('https://www.googleapis.com/auth/userinfo.email',
                'https://www.googleapis.com/auth/kintaro')


class BindingMessage(messages.Message):
    collection = messages.StringField(1)
    kintaro_collection = messages.StringField(2)


class _GoogleServicePreprocessor(grow.Preprocessor):
    _last_run = None

    def create_service(self, host):
        credentials = oauth.get_or_create_credentials(
            scope=OAUTH_SCOPES, storage_key=STORAGE_KEY)
        http = httplib2.Http(ca_certs=utils.get_cacerts_path())
        http = credentials.authorize(http)
        # Kintaro's server doesn't seem to be able to refresh expired tokens
        # properly (responds with a "Stateless token expired" error). So we
        # manage state ourselves and refresh slightly more often than once
        # per hour.
        now = datetime.datetime.now()
        if self._last_run is None \
                or now - self._last_run >= datetime.timedelta(minutes=50):
            credentials.refresh(http)
            self._last_run = now
        url = DISCOVERY_URL.replace('{host}', host)
        return discovery.build('content', 'v1', http=http,
                               discoveryServiceUrl=url)


class KintaroPreprocessor(_GoogleServicePreprocessor):
    KIND = 'kintaro'

    class Config(messages.Message):
        bind = messages.MessageField(BindingMessage, 1, repeated=True)
        repo = messages.StringField(2)
        project = messages.StringField(3)
        host = messages.StringField(4, default=KINTARO_HOST)
        use_index = messages.BooleanField(5, default=True)

    def __init__(self, *args, **kwargs):
        super(KintaroPreprocessor, self).__init__(*args, **kwargs)
        self._service = None
        self._env_regex = None
        self._env_regex_match = None
        self._env_regex_replace = r'@env.\1'

    @property
    def service(self):
        if not self._service:
            self._service = self.create_service(host=self.config.host)
        return self._service

    def bind_collection(self, entries, collection_pod_path):
        collection = self.pod.get_collection(collection_pod_path)
        if not collection.exists:
            self.pod.create_collection(collection_pod_path, {})
        existing_pod_paths = [
            doc.pod_path
            for doc in collection.docs(recursive=False, inject=False)]
        new_pod_paths = []
        for i, entry in enumerate(entries):
            # TODO: Ensure `create_doc` doesn't die if the file doesn't exist.
            basename = self._get_basename_from_entry(entry)
            path = os.path.join(collection.pod_path, basename)
            if not self.pod.file_exists(path):
                self.pod.write_yaml(path, {})
            doc_pod_path = os.path.join(collection.pod_path, basename)
            doc = collection.get_doc(doc_pod_path)
            fields, unused_body, basename = self._parse_entry(doc, entry)
            doc = collection.create_doc(basename, fields=fields, body='')
            new_pod_paths.append(doc.pod_path)
            self.pod.logger.info('Saved -> {}'.format(doc.pod_path))

        pod_paths_to_delete = set(existing_pod_paths) - set(new_pod_paths)
        for pod_path in pod_paths_to_delete:
            self.pod.delete_file(pod_path)
            self.pod.logger.info('Deleted -> {}'.format(pod_path))

    def _fix_path_none(self, key, value):
        if self._env_regex_match and self._env_regex_match.search(key):
            if key.startswith(('path', '$path')) and value is None:
                return ''
        return value

    def _regroup_schema(self, schema):
        names_to_fields = {}
        for field in schema:
            names_to_fields[field['name']] = field
        return names_to_fields

    def _parse_field(self, key, value, field_data, locale=None):
        # Convert Kintaro keys to Grow built-ins.
        if hasattr(documents, 'BUILT_IN_FIELDS'):
            built_in_fields = documents.BUILT_IN_FIELDS
        else:
            # Support older versions of grow.
            built_in_fields = ['title', 'order']

        if key in built_in_fields:
            key = '${}'.format(key)

        key = self._parse_field_key(key, field_data)

        # Need to make sure that environment tagged built ins are prefixed.
        tagged_regex = re.compile(r'^({})@'.format('|'.join(built_in_fields)))
        if tagged_regex.search(key):
            key = '${}'.format(key)

        value = self._parse_field_deep(key, value, field_data, locale=locale)
        value = self._fix_path_none(key, value)
        return key, value

    def _parse_field_deep(self, key, value, field_data, locale=None):
        single_field = not isinstance(value, list)
        if single_field:
            value = [value]

        # Handle ReferenceField as doc reference.
        if field_data['type'] == 'ReferenceField':
            for idx in range(len(value)):
                if not value[idx]:
                    continue
                for binding in self.config.bind:
                    if binding.kintaro_collection == value[idx]['collection_id']:
                        filename = '{}.yaml'.format(
                            value[idx]['document_id'])
                        content_path = os.path.join(
                            binding.collection, filename)
                        value[idx] = self.pod.get_doc(
                            content_path, locale=locale)
                        break
        elif 'schema_fields' in field_data:
            names_to_schema_fields = self._regroup_schema(
                field_data['schema_fields'])
            for idx in range(len(value)):
                value[idx] = self._parse_field_value(
                    value[idx], names_to_schema_fields,
                    locale=locale)
        if single_field:
            value = value[0]
        value = self._fix_path_none(key, value)

        return value

    def _parse_field_key(self, key, field_data):
        if field_data['translatable']:
            key = '{}@'.format(key)
        # Handle environment tagging.
        if self._env_regex:
            key = re.sub(self._env_regex, self._env_regex_replace, key)
        return key

    def _parse_field_value(self, value, names_to_schema_fields, locale=None):
        clean_value = {}
        for sub_key, sub_value in value.iteritems():
            new_key = self._parse_field_key(
                sub_key, names_to_schema_fields[sub_key])
            clean_value[new_key] = self._parse_field_deep(
                new_key, sub_value, names_to_schema_fields[sub_key],
                locale=locale)
        return clean_value

    def _get_basename_from_entry(self, entry):
        return '{}.yaml'.format(entry['document_id'])

    def _parse_entry(self, doc, entry):
        deployments = doc.pod.yaml.get('deployments', {}).keys()
        if deployments and not self._env_regex:
            self._env_regex = re.compile(
                r'_env_({})$'.format('|'.join(deployments)))
            self._env_regex_match = re.compile(
                r'@env.({})$'.format('|'.join(deployments)))
        basename = self._get_basename_from_entry(entry)
        schema = entry.get('schema', {})
        schema_fields = schema.get('schema_fields', [])
        names_to_schema_fields = self._regroup_schema(schema_fields)
        fields = entry.get('content_json', '{}')
        fields = json.loads(fields)
        clean_fields = {}
        # Preserve existing built-in fields prefixed with $.
        front_matter_data = doc.format.front_matter.data
        if front_matter_data:
            for key, value in front_matter_data.iteritems():
                if not key.startswith('$'):
                    continue
                clean_fields[key] = value
        # Overwrite with data from CMS.
        for name, value in fields.iteritems():
            field_data = names_to_schema_fields[name]
            key, value = self._parse_field(
                name, value, field_data, locale=doc.locale)
            clean_fields[key] = value
        # Populate $meta.
        if schema:
            # Strip modified info from schema.
            schema.pop('mod_info', None)
            clean_fields['$meta'] = {}
            clean_fields['$meta']['schema'] = schema
        body = ''
        return clean_fields, body, basename

    def _get_documents_from_search(self, repo_id, collection_id, project_id, documents):
        results = []
        for document in documents:
            document_id = document['document_id']
            entry = self.download_entry(
                document_id, collection_id, repo_id, project_id)
            results.append(entry)
        return results
        # TODO: Upgrade Grow's google api python client, use it to batch
        # requests.
        service = self.create_service(host=self.config.host)
        batch = service.new_batch_http_request()
        results = []

        def _add(entry):
            results.append(entry)
        for document in documents:
            document_id = document['document_id']
            req = service.documents().getDocument(
                document_id=document_id,
                collection_id=collection_id,
                project_id=project_id,
                repo_id=repo_id,
                include_schema=True,
                use_json=True)
            batch.add(req, callback=_add)
        batch.execute()
        return results

    def download_entries(self, repo_id, collection_id, project_id):
        body = {
            'repo_id': repo_id,
            'collection_id': collection_id,
            'project_id': project_id,
            'result_options': {
                'return_json': True,
                'return_schema': True,
            }
        }
        resp = self.service.documents().searchDocuments(body=body).execute()
        documents = resp.get('document_list', {}).get('documents', [])
        if not self.config.use_index:
            documents_from_get = self._get_documents_from_search(
                repo_id, collection_id, project_id, documents)
            return documents_from_get
        # Reformat document response to include schema.
        schema = resp.get('schema', {})
        for document in documents:
            document['schema'] = schema
        return documents

    def download_entry(self, document_id, collection_id, repo_id, project_id):
        resp = self.service.documents().getDocument(
            document_id=document_id,
            collection_id=collection_id,
            project_id=project_id,
            repo_id=repo_id,
            include_schema=True,
            use_json=True).execute()
        return resp

    def _normalize(self, path):
        return path.rstrip('/') if path else None

    def get_edit_url(self, doc=None):
        if not doc:
            return
        kintaro_collection = ''
        kintaro_document = doc.base
        doc_pod_path = self._normalize(doc.collection.pod_path)
        for binding in self.config.bind:
            if self._normalize(binding.collection) == doc_pod_path:
                kintaro_collection = binding.kintaro_collection
        if kintaro_collection:
            return KINTARO_EDIT_PATH_FORMAT.format(
                host=self.config.host,
                project=self.config.project,
                repo=self.config.repo,
                collection=kintaro_collection,
                document=kintaro_document)

    def can_inject(self, doc=None, collection=None):
        if not self.injected:
            return False
        if doc:
            doc_pod_path = self._normalize(doc.collection.pod_path)
            for binding in self.config.bind:
                if self._normalize(binding.collection) == doc_pod_path:
                    return True
        return False

    def inject(self, doc=None, collection=None):
        if doc:
            document_id = doc.base
            doc_pod_path = self._normalize(doc.collection.pod_path)
            for binding in self.config.bind:
                if self._normalize(binding.collection) == doc_pod_path:
                    entry = self.download_entry(
                        document_id=document_id,
                        collection_id=binding.kintaro_collection,
                        repo_id=self.config.repo,
                        project_id=self.config.project)
                    fields, _, _ = self._parse_entry(doc, entry)
                    doc.inject(fields, body='')
                    return doc

    def run(self, *args, **kwargs):
        for binding in self.config.bind:
            collection_pod_path = binding.collection
            kintaro_collection = binding.kintaro_collection
            entries = self.download_entries(
                repo_id=self.config.repo,
                collection_id=kintaro_collection,
                project_id=self.config.project)
            self.bind_collection(entries, collection_pod_path)


def schema_name_to_partial(value, sep='-', directory='views/partials',
                           use_sub_directory=False, prefix='partial'):
    """Parse a kintaro schema name to determine if it is a partial."""
    if value.lower().startswith(prefix):
        basename = value[len(prefix):]
        basename = PARTIAL_CONVERSION.sub(r'{}\1'.format(sep), basename)[1:]
        if use_sub_directory:
            directory = '{}/{}'.format(directory, basename.lower())
        return '/{}/{}.html'.format(directory, basename.lower())
    return None


class KintaroExtension(Extension):
    """Add a filter for jinja2 that assists with kintaro transformations."""

    def __init__(self, environment):
        super(KintaroExtension, self).__init__(environment)
        environment.filters[
            'kintaro.schema_name_to_partial'] = schema_name_to_partial
