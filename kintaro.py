from googleapiclient import discovery
from googleapiclient import errors
from grow.common import oauth
from grow.common import utils
from protorpc import messages
import logging
import os
import grow
import httplib2


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


class KintaroPreprocessor(grow.Preprocessor):
    KIND = 'kintaro'

    class Config(messages.Message):
        bind = messages.MessageField(BindingMessage, 1, repeated=True)
        repo = messages.StringField(2)
        project = messages.StringField(3)
        host = messages.StringField(4, default=KINTARO_HOST)
        upload = messages.BooleanField(5)
        download = messages.BooleanField(6)
        schema = messages.BooleanField(8)

    @staticmethod
    def create_service(host):
        credentials = oauth.get_or_create_credentials(
            scope=OAUTH_SCOPES, storage_key=STORAGE_KEY)
        http = httplib2.Http(ca_certs=utils.get_cacerts_path())
        http = credentials.authorize(http)
        # Kintaro's server doesn't seem to be able to refresh expired tokens
        # properly (responds with a "Stateless token expired" error). So for
        # now, automatically refresh tokens each time a service is created. If
        # this isn't fixed on the Kintaro end, what we can do is implement our
        # own refresh system (tokens need to be refreshed once per hour).
        credentials.refresh(http)
        url = DISCOVERY_URL.replace('{host}', host)
        service = discovery.build('content', 'v1', http=http,
                                  discoveryServiceUrl=url)
        return service

    def bind_collection(self, entries, collection_pod_path):
        collection = self.pod.get_collection(collection_pod_path)
        existing_pod_paths = [
            doc.pod_path
            for doc in collection.docs(recursive=False, inject=False)]
        new_pod_paths = []
        for i, entry in enumerate(entries):
            fields, unused_body, basename = self._parse_entry(collection, entry)
            doc = collection.create_doc(basename, fields=fields, body='')
            new_pod_paths.append(doc.pod_path)
            self.pod.logger.info('Saved -> {}'.format(doc.pod_path))
        pod_paths_to_delete = set(existing_pod_paths) - set(new_pod_paths)
        for pod_path in pod_paths_to_delete:
            self.pod.delete_file(pod_path)
            self.pod.logger.info('Deleted -> {}'.format(pod_path))

    def _parse_entry(self, collection, entry):
        basename = '{}.yaml'.format(entry['document_id'])
        body = None
        fields = {}
        image_url = None
        for field in entry['content'].get('fields', []):
            name = field['field_name']
            if field.get('repeated'):
                fields[name] = field['nested_field_values']
                continue
            if name == 'image':
                nested_values = field.get('nested_field_values')
                if nested_values:
                    nested_fields = nested_values[0].get('fields')
                    if nested_fields:
                        nested_field_values = nested_fields[0].get('field_values')
                        if nested_field_values:
                            image_url = nested_field_values[0]['value']
            if field.get('field_values'):
                if 'value' not in field['field_values'][0]:
                    continue
                value = field['field_values'][0]['value']
                fields[name] = value
        if 'draft' in fields:
            # TODO: Fix this.
            fields['draft'] = True if fields['draft'] == 'True' else False
        if 'order' in fields:
            fields['$order'] = int(fields.pop('order'))
        if 'title@' in fields:
            fields['$title@'] = fields.pop('title@')
        if 'title' in fields:
            fields['$title'] = fields.pop('title')
        if 'body' in fields:
            body = fields.pop('body')
        if image_url:
            fields['image_url'] = image_url + '=w2048'
        return fields, body, basename

    def run(self, *args, **kwargs):
        if self.config.schema:
            self.update_schemas()
        if self.config.upload:
            self.upload_collections()
        if self.config.download:
            self.download_collections()

    def upload_collection(self, collection):
        cms = collection.fields.get('cms')
        service = KintaroPreprocessor.create_service(host=self.config.host)
        for doc in collection.list_docs():
            fields = []
            for field in cms.get('fields', []):
                name = field['name']
                if name.startswith('cms_'):
                    continue
                values = []
                if name == 'body':
                    value = doc.format.content
                elif name == 'draft':
                    value = str(doc.fields.get(name))
                else:
                    value = doc.fields.get('$' + name) or doc.fields.get(name)
                fields.append({
                    'field_name': name,
                    'field_values': [{
                        'value': value,
                    }],
                })
            if doc.fields.get('cms_id'):
                request = {
                    'repo_id': cms['repo'],
                    'project_id': cms['repo'],
                    'collection_id': cms['collection'],
                    'update_requests': [{
                        'document_id': doc.fields.get('cms_id'),
                        'contents': {
                            'fields': fields,
                        },
                    }]
                }
                cms_id = doc.fields.get('cms_id')
                resp = service.documents().multiDocumentUpdate(body=request).execute(num_retries=3)
                self.pod.logger.info(
                    'Updated -> {}:{}:{}'.format(
                        cms['repo'], cms_id, doc.pod_path))
            else:
                request = {
                    'repo_id': cms['repo'],
                    'project_id': cms['repo'],
                    'collection_id': cms['collection'],
                    'contents': {
                        'fields': fields,
                    },
                }
                resp = service.documents().createDocument(body=request).execute(num_retries=3)
                cms_id = resp['document_id']
                self.pod.logger.info(
                    'Created -> {}:{}:{}'.format(
                        cms['repo'], cms_id, doc.pod_path))
            new_fields = doc.fields._data
            new_fields.update({'cms_id': cms_id})
            doc.format.update(fields=new_fields)
            self.pod.write_file(doc.pod_path, doc.format.to_raw_content())

    def update_schema(self, collection):
        cms = collection.fields.get('cms')
        service = KintaroPreprocessor.create_service(host=self.config.host)
        schema = {
            'repo_id': cms['repo'],
            'name': cms['collection'],
            'schema_fields': [],
        }
        for field in cms.get('fields', []):
            kwargs = {
                'name': field['name'],
                'type': field.get('type', 'StringField'),
                'displayed': 'displayed' in field,
                'indexed': 'indexed' in field,
                'repeated': 'repeated' in field,
                'label': 'label' in field,
                'description': field.get('description'),
            }
            if 'translatable' in field:
                kwargs['translatable'] = field['translatable']
            schema['schema_fields'].append(kwargs)

        try:
            resp = service.schemas().createSchema(body=schema).execute()
            self.pod.logger.info(
                    'Created schema -> {}:{}'.format(
                        cms['repo'], cms['collection']))
        except Exception as e:
            if not 'already exists in this repo' in str(e):
                raise
            resp = service.schemas().updateSchema(
                    id=cms['collection'], body=schema).execute()
            self.pod.logger.info(
                    'Updated schema -> {}:{}'.format(
                        cms['repo'], cms['collection']))

        collection_request = {}
        collection_request['collection_id'] = cms['collection']
        collection_request['repo_id'] = cms['repo']
        collection_request['schema_id'] = cms['collection']
        try:
            resp = service.collections().createCollection(
                    body=collection_request).execute()
            self.pod.logger.info(
                'Created collection -> {}:{}'.format(
                    cms['repo'], cms['collection']))
        except Exception as e:
            if not 'Already used by' in str(e):
                raise
            resp = service.collections().updateCollection(
                    path_repo_id=cms['repo'],
                    path_collection_id=cms['collection'],
                    body=collection_request).execute()
            self.pod.logger.info(
                'Updated collection -> {}:{}'.format(
                    cms['repo'], cms['collection']))

    def upload_collections(self):
        for collection in self.pod.list_collections():
            cms = collection.fields.get('cms')
            if not cms or not cms.get('upload'):
                continue
            self.upload_collection(collection)

    def update_schemas(self):
        for collection in self.pod.list_collections():
            cms = collection.fields.get('cms')
            if not cms:
                continue
            self.update_schema(collection)

    def download_collections(self):
        for collection in self.pod.list_collections():
            cms = collection.fields.get('cms')
            if not cms:
                continue
            self.download_collection(collection)

    def download_collection(self, collection):
        service = KintaroPreprocessor.create_service(host=self.config.host)
        cms = collection.fields.get('cms')
        collection_pod_path = collection.pod_path
        entries = self.download_entries(
            repo_id=cms['repo'],
            collection_id=cms['collection'],
            project_id=cms['repo'])
        for entry in entries:
            cms_id = entry['document_id']
            fields, new_body, _ = self._parse_entry(collection, entry)
            ext = '.md' if new_body else '.yaml'
            doc = self.get_doc_by_document_id(collection, cms_id, ext, fields)
            new_fields = doc.fields._data
            new_fields.update({'cms_id': cms_id})
            new_fields.update(fields)
            if new_body:
                new_body = new_body.encode('utf-8')
                doc.format.update(fields=new_fields, content=new_body)
            else:
                doc.format.update(fields=new_fields)
            self.pod.write_file(doc.pod_path, doc.format.to_raw_content())
            self.pod.logger.info('Saved {}:{} -> {}'.format(
                cms['repo'], cms_id, doc.pod_path))
#        self.bind_collection(entries, collection_pod_path)
# TODO: Implement deletes.

    def get_doc_by_document_id(self, collection, doc_id, ext, fields=None):
        for doc in collection.list_docs():
            cms_id = doc.fields.get('cms_id')
            if cms_id == doc_id:
                return doc
        title = fields.get('$title') or doc_id
        title = utils.slugify(title)
        basename = title + ext
        path = os.path.join(collection.pod_path, basename)
        path = self.pod.abs_path(path)
	fp = open(path, 'a')
	fp.write('{}')
        fp.close()
        return collection.create_doc(basename)

    def download_content(self):
        for binding in self.config.bind:
            collection_pod_path = binding.collection
            kintaro_collection = binding.kintaro_collection
            entries = self.download_entries(
                repo_id=self.config.repo,
                collection_id=kintaro_collection,
                project_id=self.config.project)
            self.bind_collection(entries, collection_pod_path)

    def download_entries(self, repo_id, collection_id, project_id):
        service = KintaroPreprocessor.create_service(host=self.config.host)
        resp = service.documents().listDocuments(
            repo_id=repo_id,
            collection_id=collection_id,
            project_id=project_id).execute()
        return resp.get('documents', [])

    def download_entry(self, document_id, collection_id, repo_id, project_id):
        service = KintaroPreprocessor.create_service(host=self.config.host)
        resp = service.documents().getDocument(
            document_id=document_id,
            collection_id=collection_id,
            project_id=project_id,
            repo_id=repo_id).execute()
        return resp

    def get_edit_url(self, doc=None):
        return ''
        kintaro_collection = ''
        kintaro_document = doc.base
        for binding in self.config.bind:
            if binding.collection == doc.collection.pod_path:
                kintaro_collection = binding.kintaro_collection
        return KINTARO_EDIT_PATH_FORMAT.format(
            host=self.config.host,
            project=self.config.project,
            repo=self.config.repo,
            collection=kintaro_collection,
            document=kintaro_document)

    def can_inject(self, doc=None, collection=None):
        if not self.injected:
            return False
        if doc is not None:
            if doc.fields.get('cms_id'):
                return True
        return False

    def inject(self, doc=None, collection=None):
        document_id = doc.base
        if doc is not None:
            cms_id = doc.fields.get('cms_id')
            cms_collection = doc.fields.get('cms_collection')
            entry = self.download_entry(
                document_id=cms_id,
                collection_id=cms_collection,
                repo_id=self.config.repo,
                project_id=self.config.project)
            fields, _, _ = self._parse_entry(doc.collection, entry)
            doc.inject(fields, body='')
            return doc
