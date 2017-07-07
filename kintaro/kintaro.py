from googleapiclient import discovery
from googleapiclient import errors
from grow.common import oauth
from grow.common import utils
from protorpc import messages
import datetime
import grow
import httplib2
import json
import logging
import os


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

    def bind_collection(self, entries, collection_pod_path):
        collection = self.pod.get_collection(collection_pod_path)
        existing_pod_paths = [
            doc.pod_path
            for doc in collection.docs(recursive=False, inject=False)]
        new_pod_paths = []
        for i, entry in enumerate(entries):
            fields, unused_body, basename = self._parse_entry(entry)
            # TODO: Ensure `create_doc` doesn't die if the file doesn't exist.
            path = os.path.join(collection.pod_path, basename)
            if not self.pod.file_exists(path):
                self.pod.write_yaml(path, {})
            doc = collection.create_doc(basename, fields=fields, body='')
            new_pod_paths.append(doc.pod_path)
            self.pod.logger.info('Saved -> {}'.format(doc.pod_path))

        pod_paths_to_delete = set(existing_pod_paths) - set(new_pod_paths)
        for pod_path in pod_paths_to_delete:
            self.pod.delete_file(pod_path)
            self.pod.logger.info('Deleted -> {}'.format(pod_path))

    def _regroup_schema(self, schema):
        names_to_fields = {}
        for field in schema:
            names_to_fields[field['name']] = field
        return names_to_fields

    def _parse_field(self, key, value, field_data):
        # Convert Kintaro keys to Grow built-ins.
        if key == 'title':
            key = '$title'
        elif key == 'order':
            key = '$order'
        if field_data['translatable']:
            key = '{}@'.format(key)
        return key, value

    def _parse_entry(self, entry):
        basename = '{}.yaml'.format(entry['document_id'])
        schema = entry.get('schema', {})
        schema_fields = schema.get('schema_fields', [])
        names_to_schema_fields = self._regroup_schema(schema_fields)
        fields = entry.get('content_json', '{}')
        fields = json.loads(fields)
        clean_fields = {}
        for name, value in fields.iteritems():
            field_data = names_to_schema_fields[name]
            key, value = self._parse_field(name, value, field_data)
            clean_fields[key] = value
        # Populate $meta.
        if schema:
            # Strip modified info from schema.
            schema.pop('mod_info', None)
            clean_fields['$meta'] = {}
            clean_fields['$meta']['schema'] = schema
        body = ''
        return clean_fields, body, basename

    def download_entries(self, repo_id, collection_id, project_id):
        service = self.create_service(host=self.config.host)
        body = {
            'repo_id': repo_id,
            'collection_id': collection_id,
            'project_id': project_id,
            'result_options': {
                'return_json': True,
                'return_schema': True,
            }
        }
        resp = service.documents().searchDocuments(body=body).execute()
        documents = resp.get('document_list', {}).get('documents', [])
        schema = resp.get('schema', {})
        # Reformat document response to include schema.
        for document in documents:
            document['schema'] = schema
        return documents

    def download_entry(self, document_id, collection_id, repo_id, project_id):
        service = self.create_service(host=self.config.host)
        resp = service.documents().getDocument(
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
                    fields, _, _ = self._parse_entry(entry)
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
