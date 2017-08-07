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

import json
import re
import urllib
import urlparse

from resources.lib.modules import anilist
from resources.lib.modules import cleantitle
from resources.lib.modules import client
from resources.lib.modules import source_utils
from resources.lib.modules import dom_parser
from resources.lib.modules import tvmaze

class source:
    def __init__(self):
        self.priority = 1
        self.language = ['de']
        self.genre_filter = ['animation', 'anime']
        self.domains = ['anime-loads.org']
        self.base_link = 'http://www.anime-loads.org'
        self.search_link = '/search?q=%s'

    def movie(self, imdb, title, localtitle, aliases, year):
        try:
            url = self.__search([title, localtitle, anilist.getAlternativTitle(title)] + source_utils.aliases_to_array(aliases), year)
            return urllib.urlencode({'url': url}) if url else None
        except:
            return

    def tvshow(self, imdb, tvdb, tvshowtitle, localtvshowtitle, aliases, year):
        try:
            url = self.__search([tvshowtitle, localtvshowtitle, tvmaze.tvMaze().showLookup('thetvdb', tvdb).get('name')] + source_utils.aliases_to_array(aliases), year)
            return urllib.urlencode({'url': url}) if url else None
        except:
            return

    def episode(self, url, imdb, tvdb, title, premiered, season, episode):
        try:
            if not url:
                return

            episode = tvmaze.tvMaze().episodeAbsoluteNumber(tvdb, int(season), int(episode))

            data = urlparse.parse_qs(url)
            data = dict([(i, data[i][0]) if data[i] else (i, '') for i in data])
            data.update({'episode': episode})
            return urllib.urlencode(data)
        except:
            return

    def sources(self, url, hostDict, hostprDict):
        sources = []

        try:
            if not url:
                return sources

            data = urlparse.parse_qs(url)
            data = dict([(i, data[i][0]) if data[i] else (i, '') for i in data])
            url = data.get('url')
            episode = int(data.get('episode', 1))

            r = client.request(urlparse.urljoin(self.base_link, url))
            r = dom_parser.parse_dom(r, 'div', attrs={'id': 'streams'})

            rels = dom_parser.parse_dom(r, 'ul', attrs={'class': 'nav'})
            rels = dom_parser.parse_dom(rels, 'li')
            rels = dom_parser.parse_dom(rels, 'a', attrs={'href': re.compile('#stream_\d*')}, req='href')
            rels = [(re.findall('stream_(\d+)', i.attrs['href']), re.findall('flag-(\w{2})', i.content)) for i in rels if i]
            rels = [(i[0][0], ['subbed'] if i[1][0] != 'de' else []) for i in rels if i[0] and 'de' in i[1]]

            for id, info in rels:
                rel = dom_parser.parse_dom(r, 'div', attrs={'id': 'stream_%s' % id})
                rel = [(dom_parser.parse_dom(i, 'div', attrs={'id': 'streams_episodes_%s' % id}), dom_parser.parse_dom(i, 'tr')) for i in rel]
                rel = [(i[0][0].content, [x for x in i[1] if 'fa-desktop' in x.content]) for i in rel if i[0] and i[1]]
                rel = [(i[0], dom_parser.parse_dom(i[1][0].content, 'td')) for i in rel if i[1]]
                rel = [(i[0], re.findall('\d{3,4}x(\d{3,4})$', i[1][0].content)) for i in rel if i[1]]
                rel = [(i[0], source_utils.label_to_quality(i[1][0])) for i in rel if len(i[1]) > 0]

                for html, quality in rel:
                    try:
                        s = dom_parser.parse_dom(html, 'a', attrs={'href': re.compile('#streams_episodes_%s_\d+' % id)})
                        s = [(dom_parser.parse_dom(i, 'div', attrs={'data-loop': re.compile('\d+')}, req='data-loop'), dom_parser.parse_dom(i, 'span')) for i in s]
                        s = [(i[0][0].attrs['data-loop'], [x.content for x in i[1] if '<strong' in x.content]) for i in s if i[0]]
                        s = [(i[0], re.findall('<.+?>(\d+)</.+?> (.+?)$', i[1][0])) for i in s if len(i[1]) > 0]
                        s = [(i[0], i[1][0]) for i in s if len(i[1]) > 0]
                        s = [(i[0], int(i[1][0]), re.findall('Episode (\d+):', i[1][1]), re.IGNORECASE) for i in s if len(i[1]) > 1]
                        s = [(i[0], i[1], int(i[2][0]) if len(i[2]) > 0 else -1) for i in s]
                        s = [(i[0], i[2] if i[2] >= 0 else i[1]) for i in s]
                        s = [i[0] for i in s if i[1] == episode][0]

                        enc = dom_parser.parse_dom(html, 'div', attrs={'id': re.compile('streams_episodes_%s_%s' % (id, s))}, req='data-enc')[0].attrs['data-enc']

                        hosters = dom_parser.parse_dom(html, 'a', attrs={'href': re.compile('#streams_episodes_%s_%s' % (id, s))})
                        hosters = [dom_parser.parse_dom(i, 'i', req='class') for i in hosters]
                        hosters = [re.findall('hoster-(\w+)', ' '.join([x.attrs['class'] for x in i])) for i in hosters if i][0]
                        hosters = [(source_utils.is_host_valid(re.sub('(co|to|net|pw|sx|tv|moe|ws|icon)$', '', i), hostDict), i) for i in hosters]
                        hosters = [(i[0][1], i[1]) for i in hosters if i[0] and i[0][0]]

                        info = ' | '.join(info)

                        for source, hoster in hosters:
                            sources.append({'source': source, 'quality': quality, 'language': 'de', 'url': [enc, hoster], 'info': info, 'direct': False, 'debridonly': False, 'checkquality': True})
                    except:
                        pass

            return sources
        except:
            return sources

    def resolve(self, url):
        try: return al()._resolve(url)
        except: return

    def __search(self, titles, year):
        try:
            query = self.search_link % (urllib.quote_plus(cleantitle.query(titles[0])))
            query = urlparse.urljoin(self.base_link, query)

            t = [cleantitle.get(i) for i in set(titles) if i]

            r = client.request(query)

            r = dom_parser.parse_dom(r, 'div', attrs={'id': 'main'})
            r = dom_parser.parse_dom(r, 'div', attrs={'class': 'panel-body'})
            r = [(dom_parser.parse_dom(i.content, 'h4', attrs={'class': 'title-list'}), dom_parser.parse_dom(i.content, 'a', attrs={'href': re.compile('.*/year/.*')})) for i in r]
            r = [(dom_parser.parse_dom(i[0][0].content, 'a', req='href'), i[1][0].content if i[1] else '0') for i in r if i[0]]
            r = [(i[0][0].attrs['href'], i[0][0].content, re.sub('<.+?>|</.+?>', '', i[1])) for i in r if i[0] and i[1]]
            r = [(i[0], i[1], i[2].strip()) for i in r if i[2]]
            r = sorted(r, key=lambda i: int(i[2]), reverse=True)  # with year > no year
            r = [i[0] for i in r if cleantitle.get(i[1]) in t and i[2] == year][0]

            return source_utils.strip_domain(r)
        except:
            return

# Bubbles Removed
# Exclusive to Exodus