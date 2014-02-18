# Copyright (c) 2013 Qubell Inc., http://qubell.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


__author__ = "Vasyl Khomenko"
__copyright__ = "Copyright 2013, Qubell.com"
__license__ = "Apache"
__email__ = "vkhomenko@qubell.com"

import logging as log

import requests
import simplejson as json

from qubell.api.private import exceptions
from qubell.api.private.common import Qubell_object_list


class Applications(Qubell_object_list):
    def __init__(self, organization):
        self.organization = organization
        self.auth = self.organization.auth
        self.organizationId = self.organization.organizationId
        self.object_list = []
        self.__generate_object_list()

    def __generate_object_list(self):
        from qubell.api.private.application import Application
        for app in self.organization.list_applications_json():
            self.object_list.append(Application(self.auth, self.organization, id=app['id']))


class Application(object):
    """
    Base class for applications. It should create application and services+environment requested
    """

    def __update(self):
        info = self.json()
        self.name = info['name']
        self.id = self.applicationId


    def __init__(self, auth, organization, **kwargs):
        # TODO: self.instances = organization

        if hasattr(self, 'applicationId'):
            log.warning("Application reinitialized. Dangerous!")
        self.revisions = []
        self.auth = auth
        self.organization = organization
        self.organizationId = self.organization.organizationId
        self.defaultEnvironment = self.organization.get_default_environment()
        if 'id' in kwargs:
            self.applicationId = kwargs.get('id')
            self.__update()

    def __parse(self, values):
        ret = {}
        for val in values:
            ret[val['id']] = val['value']
        return ret

        #TODO: Think how to restore revisions

    def create(self, name, manifest):
        log.info("Creating application: %s" % name)
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications.json'

        resp = requests.post(url, files={'path': manifest.content}, data={'manifestSource': 'upload', 'name': name}, verify=False, cookies=self.auth.cookies)
        log.debug(resp.text)
        if resp.status_code == 200:
            self.applicationId = resp.json()['id']
            self.manifest = manifest
            self.__update()
            return self
        raise exceptions.ApiError('Unable to create application %s, got error: %s' % (name, resp.text))

    def delete(self):
        log.info("Removing application: %s" % self.name)
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'.json'
        resp = requests.delete(url, verify=False, cookies=self.auth.cookies)
        log.debug(resp.text)
        if resp.status_code == 200:
            return True
        raise exceptions.ApiError('Unable to delete application: %s' % resp.text)

    def update(self, **kwargs):
        if kwargs.get('manifest'):
            self.upload(kwargs.pop('manifest'))
        log.info("Updating application: %s" % self.name)
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'.json'
        headers = {'Content-Type': 'application/json'}
        data = json.dumps(kwargs)
        resp = requests.put(url, headers=headers, verify=False, data=data, cookies=self.auth.cookies)
        log.debug(resp.text)
        if resp.status_code == 200:
            self.__update()
            return resp.json()
        raise exceptions.ApiError('Unable to update application %s, got error: %s' % (self.name, resp.text))

    def clean(self, timeout=3):
        for ins in self.instances:
            st = ins.status
            if st not in ['Destroyed', 'Destroying', 'Launching', 'Executing']: # Tests could fail and we can get any statye here
                log.info("Destroying instance %s" % ins.name)
                ins.delete()
                assert ins.destroyed(timeout=timeout)
                self.instances.remove(ins)

        for rev in self.revisions:
            self.revisions.remove(rev)
            rev.delete()
        return True

    def json(self):
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'.json'
        resp = requests.get(url, cookies=self.auth.cookies, data="{}", verify=False)
        log.debug(resp.text)
        if resp.status_code == 200:
            return resp.json()
        raise exceptions.ApiError('Unable to get application by url %s\n, got error: %s' % (url, resp.text))

    def __getattr__(self, key):
        resp = self.json()
        if not resp.has_key(key):
            raise exceptions.NotFoundError('Cannot get property %s' % key)
        return resp[key] or False


# REVISION
    def get_revision(self, id):
        from qubell.api.private.revision import Revision
        rev = Revision(auth=self.auth, application=self, id=id)
        self.revisions.append(rev)
        return rev

    def list_revisions(self):
        return self.revisions()

    def create_revision(self, name, instance, parameters=[], version=None):
        if not version:
            version=self.get_manifest()['manifestVersion']
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'/revisions.json'
        headers = {'Content-Type': 'application/json'}
        payload = json.dumps({ 'name': name,
                    'parameters': parameters,
                    'submoduleRevisions': {},
                    'returnValues': [],
                    'applicationId': self.applicationId,
                    'applicationName': self.name,
                    'version': version,
                    'instanceId': instance.instanceId})
        resp = requests.post(url, cookies=self.auth.cookies, data=payload, verify=False, headers=headers)
        log.debug(resp.text)
        if resp.status_code == 200:
            return self.get_revision(id=resp.json()['id'])
        raise exceptions.ApiError('Unable to get revision, got error: %s' % resp.text)

    def delete_revision(self, id):
        rev = self.get_revision(id)
        self.revisions.remove(rev.name)
        rev.delete()

# MANIFEST

    def get_manifest(self):
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'/refreshManifest.json'
        headers = {'Content-Type': 'application/json'}
        payload = json.dumps({})
        resp = requests.post(url, cookies=self.auth.cookies, data=payload, verify=False, headers=headers)
        log.debug(resp.text)

        if resp.status_code == 200:
            return resp.json()
        raise exceptions.ApiError('Unable to get manifest, got error: %s' % resp.text)

    def upload(self, manifest):
        log.info("Uploading manifest")
        url = self.auth.api+'/organizations/'+self.organizationId+'/applications/'+self.applicationId+'/manifests.json'
        resp = requests.post(url, files={'path': manifest.content}, data={'manifestSource': 'upload', 'name': self.name}, verify=False, cookies=self.auth.cookies)
        log.debug(resp.text)
        if resp.status_code == 200:
            self.manifest = manifest
            return resp.json()
        raise exceptions.ApiError('Unable to upload manifest, got error: %s' % resp.text)
