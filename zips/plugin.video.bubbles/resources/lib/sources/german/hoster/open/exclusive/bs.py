# -*- coding: utf-8 -*-

"""
    Exodus Add-on
    Copyright (C) 2016 Exodus

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import re
import json
import urlparse

from resources.lib.modules import cache
from resources.lib.modules import cleantitle
from resources.lib.modules import client
from resources.lib.modules import source_utils


class source:
    def __init__(self):
        self.priority = 1
        self.language = ['de']
        self.domains = ['bs.to']
        self.base_link = 'https://www.bs.to/'
        self.api_link = 'api/%s'

    def tvshow(self, imdb, tvdb, tvshowtitle, localtvshowtitle, aliases, year):
        try:
            url = self.__search([localtvshowtitle] + source_utils.aliases_to_array(aliases), year)
            if not url and tvshowtitle != localtvshowtitle: url = self.__search([tvshowtitle] + source_utils.aliases_to_array(aliases), year)
            return url
        except:
            return

    def episode(self, url, imdb, tvdb, title, premiered, season, episode):
        try:
            if not url: return
            return url + "%s/%s" % (season, episode)
        except:
            return

    def sources(self, url, hostDict, hostprDict):
        sources = []

        try:
            if not url:
                return sources

            j = self.__get_json(url)
            j = [i for i in j['links'] if 'links' in j]
            j = [(i['hoster'].lower(), i['id']) for i in j]
            j = [(re.sub('hd$', '', i[0]), i[1], 'HD' if i[0].endswith('hd') else 'SD') for i in j]
            j = [(i[0], i[1], i[2]) for i in j]

            for hoster, url, quality in j:
                valid, hoster = source_utils.is_host_valid(hoster, hostDict)
                if not valid: continue
                sources.append({'source': hoster, 'quality': quality, 'language': 'de', 'url': ('watch/%s' % url), 'direct': False, 'debridonly': False})

            return sources
        except:
            return sources

    def resolve(self, url):
        try: return self.__get_json(url)['fullurl']
        except: return

    def __get_json(self, api_call):
        try:
            headers = bs_finalizer().get_header(api_call)
            result = client.request(urlparse.urljoin(self.base_link, self.api_link % api_call), headers=headers)
            return json.loads(result)
        except:
            return

    def __search(self, titles, year):
        try:
            t = [cleantitle.get(i) for i in set(titles) if i]
            y = ['%s' % str(year), '%s' % str(int(year) + 1), '%s' % str(int(year) - 1), '0']

            r = cache.get(self.__get_json, 12, "series")
            r = [(i.get('id'), i.get('series')) for i in r]
            r = [(i[0], i[1], re.findall('(.+?) \((\d{4})\)?', i[1])) for i in r if cleantitle.get(i[1]) in t]
            r = [(i[0], i[2][0][0] if len(i[2]) > 0 else i[1], i[2][0][1] if len(i[2]) > 0 else '0') for i in r]
            r = sorted(r, key=lambda i: int(i[2]), reverse=True)  # with year > no year
            r = [i[0] for i in r if i[2] in y][0]

            return 'series/%s/' % r
        except:
            return


#############################################################

# Bubbles Removed
# Exclusive to Exodus