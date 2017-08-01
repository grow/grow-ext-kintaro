from google.appengine.ext import vendor
vendor.add('lib')

from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(60)

from google.appengine.api import app_identity
from google.appengine.ext import ndb
from googleapiclient import discovery
from googleapiclient import errors
from oauth2client.contrib import appengine
import datetime
import httplib2
import logging
import urllib2
import webapp2

# Silence extra logging from googleapiclient.
discovery.logger.setLevel(logging.WARNING)

KINTARO_HOST = 'kintaro-content-server.appspot.com'
KINTARO_API_ROOT = 'https://{host}/_ah/api'.format(host=KINTARO_HOST)
DISCOVERY_URL = (
    KINTARO_API_ROOT + '/discovery/v1/apis/{api}/{apiVersion}/rest')
SCOPE = ('https://www.googleapis.com/auth/userinfo.email',
         'https://www.googleapis.com/auth/kintaro')

APPID = app_identity.get_application_id()
SERVICE_ACCOUNT_EMAIL = '{}@appspot.gserviceaccount.com'.format(APPID)


def create_service():
    credentials = appengine.AppAssertionCredentials(SCOPE)
    http = httplib2.Http()
    http = credentials.authorize(http)
    credentials.refresh(http)
    return discovery.build('content', 'v1', http=http,
                           discoveryServiceUrl=DISCOVERY_URL)


class Watch(ndb.Model):
    last_run = ndb.DateTimeProperty()
    modified = ndb.DateTimeProperty()
    modified_by = ndb.StringProperty()
    project_id = ndb.StringProperty()
    repo_id = ndb.StringProperty()
    request_method = ndb.StringProperty()
    webhook_url = ndb.StringProperty()

    def __repr__(self):
        return '<Watch {}:{}/{}>'.format(
                self.key.id(), self.repo_id, self.project_id)

    def execute(self, kintaro, force=False):
        try:
            project = kintaro.projects().rpcGetProject(body={
                'project_id': self.project_id,
            }).execute()
        except errors.HttpError as e:
            logging.exception('Error fetching -> {}'.format(self))
            return
        self.modified_by = project['mod_info'].get('updated_by')
        self.modified = datetime.datetime.fromtimestamp(
                int(project['mod_info']['updated_on_millis']) / 1000.0)
        if force or self.last_run is None or self.modified > self.last_run:
            if self.webhook_url:
                self.run_webhook(project)
            else:
                logging.info('Skipping (no webhook) -> {}'.format(self))
        else:
            logging.info('Skipping (up-to-date) -> {}'.format(self))
        self.last_run = datetime.datetime.now()
        self.put()

    def run_webhook(self, project):
        url = self.create_webhook_url(project)
	req = urllib2.Request(url)
	req.add_header('Content-Type', 'application/json')
	resp = urllib2.urlopen(req, '{}')
        logging.info('Webhook run -> {} ({})'.format(self, url))

    def create_webhook_url(self, project):
        kwargs = {
                'project_created': project['mod_info']['created_on_millis'],
                'project_created_by': project['mod_info']['created_by'],
                'project_id': project['project_id'],
                'project_modified': project['mod_info']['updated_on_millis'],
                'project_modified_by': project['mod_info'].get('updated_by'),
                'repo_id': project['repo_ids'][0],
                'translations_up_to_date': project['translations_up_to_date'],
        }
        return self.webhook_url.format(**kwargs)


def process(force=False):
    service = create_service()
    query = Watch.query()
    results = query.fetch()
    for result in results:
        result.execute(service, force=force)


class CronHandler(webapp2.RequestHandler):

    def get(self):
        process()


class RunHandler(webapp2.RequestHandler):

    def get(self):
        process(force=True)


class WatchHandler(webapp2.RequestHandler):

    def get(self):
        query = Watch.query()
        results = query.fetch()
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write(
            'Share Kintaro with -> {}\n'.format(SERVICE_ACCOUNT_EMAIL))
        for result in results:
            self.response.out.write('{} -> {}\n'.format(result, result.webhook_url))


app = webapp2.WSGIApplication([
    ('/cron', CronHandler),
    ('/run', RunHandler),
    ('/', WatchHandler),
])
