# -*- coding: utf-8 -*-

'''
	Bubbles Add-on
	Copyright (C) 2016 Bubbles

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
'''


import xbmc,xbmcgui,xbmcvfs,sys,pkgutil,re,json,urllib,urlparse,random,datetime,time,os
import copy
from threading import Lock

from resources.lib.modules import control
from resources.lib.modules import cleantitle
from resources.lib.modules import client
from resources.lib.modules import cache
from resources.lib.modules import debrid
from resources.lib.modules import workers
from resources.lib.modules import trakt
from resources.lib.modules import tvmaze
from resources.lib.extensions import network
from resources.lib.extensions import interface
from resources.lib.extensions import tools
from resources.lib.extensions import convert
from resources.lib.extensions import handler
from resources.lib.extensions import downloader
from resources.lib.extensions import history
from resources.lib.extensions import provider
from resources.lib.extensions import debrid as debridx
from resources.lib.extensions import metadata as metadatax
from resources.lib.externals.beautifulsoup import BeautifulSoup

try: from sqlite3 import dbapi2 as database
except: from pysqlite2 import dbapi2 as database

class sources:

	def __init__(self, type = tools.Media.TypeNone, kids = tools.Selection.TypeUndefined):
		self.type = type
		self.kids = kids
		self.getConstants()
		self.sources = []
		self.providers = []
		self.progressDialog = None

	def parameterize(self, action, type = None):
		if type == None: type = self.type
		if not type == None: action += '&type=%s' % type
		if not self.kids == None: action += '&kids=%d' % self.kids
		return action

	def kidsOnly(self):
		return self.kids == tools.Selection.TypeInclude

	def playExact(self, terms = None):
		if not tools.Settings.getBoolean('internal.search.exact'):
			interface.Dialog.confirm(title = 32010, message = 35159)
			tools.Settings.set('internal.search.exact', True)

		if terms == None: terms = interface.Dialog.input(title = 35158, type = interface.Dialog.InputAlphabetic)

		if not terms == None and not terms == '':
			if self.type == tools.Media.TypeEpisode or self.type == tools.Media.TypeShow:
				return self.play(None, None, None, None, None, None, terms, None, None, None, None, None, True)
			else:
				return self.play(terms, None, None, None, None, None, None, None, None, None, None, None, True)

	def play(self, title, year, imdb, tvdb, season, episode, tvshowtitle, premiered, meta, select, preset = None, seasoncount = None, exact = False):
		try:
			if tools.Donations.popup():
				interface.Loader.hide() # Other function calling this one have a Loader (alterSources, presetSources)
				return None

			interface.Loader.show()
			source = None

			if isinstance(meta, basestring):
				metadata = json.loads(meta)
			else:
				metadata = meta

			title = tvshowtitle if tvshowtitle else title
			try: adapatedTitle = '%s S%02dE%02d' % (tvshowtitle, int(season), int(episode)) if tvshowtitle else title
			except: adapatedTitle = title

			if not select == None: select = int(select)

			# Must be done before setting select.
			autoplay = select == 2 or (select == None and tools.Settings.getBoolean('playback.automatic.enabled'))
			if control.window.getProperty('PseudoTVRunning') == 'True': autoplay = True

			if select == None: select = tools.Settings.getInteger('interface.stream.list')
			selectDirectory = select == 0

			# When the play action is called from the skin's widgets.
			if selectDirectory and not 'plugin' in control.infoLabel('Container.PluginName'):
				control.execute('RunAddon(%s)' % tools.System.id())

			result = self.getSources(title, year, imdb, tvdb, season, episode, tvshowtitle, premiered, metadata, preset = preset, seasoncount = seasoncount, exact = exact, autoplay = autoplay)
			if result == 'unavailable': # Avoid the no-streams notification right after the unavailable notification
				if self.progressDialog: self.progressDialog.close()
				interface.Loader.hide()
				return None

			if autoplay:
				originalSources = list(self.sources) # Make a copy
				self.sourcesFilter(True, adapatedTitle, metadata)
				if len(self.sources) == 0:
					self.sources = originalSources
					self.sourcesFilter(True, adapatedTitle, metadata)
					autoplay = False
			else:
				self.sourcesFilter(False, adapatedTitle, metadata)

			if len(self.sources) > 0:
				def populateDirectory():
					# Metadata is not JSON serializable.
					sources = self.sources
					for i in range(len(sources)):
						sources[i]['metadata'] = metadatax.Metadata.uninitialize(sources[i])
					sources = json.dumps(sources)

					control.window.clearProperty(self.itemProperty)
					control.window.setProperty(self.itemProperty, sources)
					control.window.clearProperty(self.metaProperty)
					control.window.setProperty(self.metaProperty, meta)
					control.sleep(200)
					command = '%s?action=addItem' % sys.argv[0]
					command = self.parameterize(command)

					return control.execute('Container.Update(%s)' % command)

				if autoplay:
					source = self.sourcesDirect(self.sources, title, year, season, episode, imdb, tvdb, metadata)
					# In case the auto play fails, show normal dialog of all streams.
					# Reset the sources, because the filter settings for auto and manual play may differ.

					if not source or source == '':
						self.sources = originalSources
						self.sourcesFilter(False, adapatedTitle, metadata)
						if len(self.sources) > 0:
							if selectDirectory:
								result = populateDirectory()
								if self.progressDialog: self.progressDialog.close()
								return result
							else:
								source = self.sourcesDialog(self.sources, metadata)
					else:
						if self.progressDialog: self.progressDialog.close()
						return source['urlresolved'] # Already playing from sourcesDirect.
				elif selectDirectory:
					result = populateDirectory()
					if self.progressDialog: self.progressDialog.close()
					return result
				else:
					source = self.sourcesDialog(self.sources, metadata)

			if source == None:
				if self.progressDialog: self.progressDialog.close()
				return self.errorForSources()
			elif source == '': # sourcesDialog()
				if self.progressDialog: self.progressDialog.close()
				return None

			if self.progressDialog: self.progressDialog.close()
			interface.Loader.hide() # if sourcesDialog is canceled, busy icon keeps going.

			from resources.lib.modules.player import player
			player().run(title, year, season, episode, imdb, tvdb, source['urlresolved'], metadata, source = source)
		except:
			tools.Logger.error()
			if self.progressDialog: self.progressDialog.close()
			interface.Loader.hide() # In case playback fails and the loader is still shown from getSources.


	def addItem(self, items = None, metadata = None):
		control.playlist.clear()

		if items == None:
			items = control.window.getProperty(self.itemProperty)
			items = json.loads(items)

		if items == None or len(items) == 0:
			control.idle()
			sys.exit()

		if metadata == None:
			try:
				metadata = control.window.getProperty(self.metaProperty)
				metadata = json.loads(metadata)
			except:
				metadata = None

		sysaddon = sys.argv[0]
		syshandle = int(sys.argv[1])

		manualEnabled = downloader.Downloader(downloader.Downloader.TypeManual).enabled(notification = False, full = True)
		cacheEnabled = downloader.Downloader(downloader.Downloader.TypeCache).enabled(notification = False, full = True)

		sysmeta = urllib.quote_plus(json.dumps(metadata))

		try: poster = metadata['poster'] if 'poster' in metadata else metadata['poster2'] if 'poster2' in metadata else metadata['poster3'] if 'poster3' in metadata else '0'
		except: poster = None
		try: fanart = metadata['fanart'] if 'fanart' in metadata else metadata['fanart2'] if 'fanart2' in metadata else metadata['fanart3'] if 'fanart3' in metadata else '0'
		except: fanart = None
		try: banner = metadata['banner'] if 'banner' in metadata else '0'
		except: banner = None
		try: thumb = metadata['thumb'] if 'thumb' in metadata else poster
		except: thumb = None

		if poster == '0': poster = control.addonPoster()
		if banner == '0' and poster == '0': banner = control.addonBanner()
		elif banner == '0': banner = poster
		if thumb == '0' and fanart == '0': thumb = control.addonFanart()
		elif thumb == '0': thumb = fanart
		if control.setting('interface.fanart') == 'true' and not fanart == '0': pass
		else: fanart = control.addonFanart()

		try: sysimage = urllib.quote_plus(poster.encode('utf-8'))
		except: sysimage = ''

		for i in range(len(items)):
			try:
				meta = metadatax.Metadata.initialize(items[i])
				items[i]['metadata'] = meta

				items[i]['information'] = metadata # Used by Quasar. Do not use the name 'metadata', since that is checked in sourcesResolve().

				label = items[i]['label']
				local = 'local' in items[i] and items[i]['local']

				jsonItem = items[i]
				jsonItem['metadata'] = metadatax.Metadata.uninitialize(jsonItem)
				syssource = urllib.quote_plus(json.dumps([jsonItem]))

				if not local and tools.Settings.getBoolean('downloads.cache.enabled'):
					sysurl = '%s?action=cacheItem&handleMode=%s&source=%s&metadata=%s' % (sysaddon, handler.Handler.ModeDefault, syssource, sysmeta)
				else:
					sysurl = '%s?action=playItem&handleMode=%s&source=%s&metadata=%s' % (sysaddon, handler.Handler.ModeDefault, syssource, sysmeta)
				sysurl = self.parameterize(sysurl)

				# ITEM

				item = control.item(label = label)

				item.setArt({'icon': thumb, 'thumb': thumb, 'poster': poster, 'banner': banner})
				if not fanart == None: item.setProperty('Fanart_Image', fanart)

				item.setInfo(type = 'Video', infoLabels = metadata)
				if meta:
					width, height = meta.videoQuality(True)
					item.addStreamInfo('video', {'codec': meta.videoCodec(True), 'width' : width, 'height': height})
					item.addStreamInfo('audio', {'codec': meta.audioCodec(True), 'channels': meta.audioChannels(True)})

				# CONTEXT MENU

				contextMenu = []
				contextWith = handler.Handler(items[i]['source']).supportedCount(items[i]) > 1

				contextLabel = interface.Translation.string(33379)
				contextCommand = '%s?action=showDetails&source=%s&metadata=%s' % (sysaddon, syssource, sysmeta)
				contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

				contextLabel = interface.Translation.string(33031)
				contextCommand = '%s?action=copyLink&source=%s&resolve=%s' % (sysaddon, syssource, network.Networker.ResolveProvider)
				contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

				contextLabel = interface.Translation.string(32070)
				contextCommand = '%s?action=traktManager&refresh=0&' % sysaddon
				if metadata:
					if 'tvdb' in metadata:
						contextCommand += 'tvdb=%s' % metadata['tvdb']
						if 'season' in metadata:
							contextCommand += '&season=%s' % str(metadata['season'])
						if 'episode' in metadata:
							contextCommand += '&episode=%s' % str(metadata['episode'])
					else:
						contextCommand += 'imdb=%s' % metadata['imdb']
				contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

				if not local:

					if manualEnabled:
						# Download Manager
						if not self.kidsOnly() and control.setting('downloads.manual.enabled') == 'true':
							contextLabel = interface.Translation.string(33585)
							contextCommand = '%s?action=downloadsManager' % (sysaddon)
							contextMenu.append((contextLabel, 'Container.Update(%s)' % self.parameterize(contextCommand)))

						# Download With
						if contextWith:
							contextLabel = interface.Translation.string(33562)
							contextCommand = '%s?action=download&downloadType=%s&handleMode=%s&image=%s&source=%s&metadata=%s' % (sysaddon, downloader.Downloader.TypeManual, handler.Handler.ModeSelection, sysimage, syssource, sysmeta)
							contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

						# Download
						contextLabel = interface.Translation.string(33051)
						contextCommand = '%s?action=download&downloadType=%s&handleMode=%s&image=%s&source=%s&metadata=%s' % (sysaddon, downloader.Downloader.TypeManual, handler.Handler.ModeDefault, sysimage, syssource, sysmeta)
						contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

					if cacheEnabled:
						# Cache With
						if contextWith:
							contextLabel = interface.Translation.string(33563)
							contextCommand = '%s?action=cacheItem&handleMode=%s&source=%s&metadata=%s' % (sysaddon, handler.Handler.ModeSelection, syssource, sysmeta)
							contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

						# Cache
						contextLabel = interface.Translation.string(33016)
						contextCommand = '%s?action=cacheItem&handleMode=%s&source=%s&metadata=%s' % (sysaddon, handler.Handler.ModeDefault, syssource, sysmeta)
						contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

					# Play With
					if contextWith:
						contextLabel = interface.Translation.string(33561)
						contextCommand = '%s?action=playItem&handleMode=%s&source=%s&metadata=%s' % (sysaddon, handler.Handler.ModeSelection, syssource, sysmeta)
						contextMenu.append((contextLabel, 'RunPlugin(%s)' % self.parameterize(contextCommand)))

				item.addContextMenuItems(contextMenu)

				# ADD ITEM

				control.addItem(handle = syshandle, url = sysurl, listitem = item, isFolder = False)
			except:
				tools.Logger.error()

		control.content(syshandle, 'files')
		control.directory(syshandle, cacheToDisc = True)

	def cacheItem(self, source, metadata = None, handleMode = None):
		try:
			if tools.Settings.getBoolean('downloads.cache.enabled'):
				interface.Loader.show()

				if metadata == None:
					metadata = control.window.getProperty(self.metaProperty)
					metadata = json.loads(metadata)

				item = source
				if isinstance(item, list):
					item = item[0]

				handle = handler.Handler().serviceDetermine(mode = handleMode, item = item, popups = True)
				if handle == handler.Handler.ReturnUnavailable or handle == handler.Handler.ReturnExternal or handle == handler.Handler.ReturnCancel:
					interface.Loader.hide()
					return None

				link = self.sourcesResolve(item, handle = handle, handleMode = handleMode, handleClose = False) # Do not use item['urlresolved'], because it has the | HTTP header part removed, which is needed by the downloader.

				# If the Premiumize download is still running and the user clicks cancel in the dialog.
				if link == None or link == '':
					return

				if 'local' in item and item['local']: # Must be after self.sourcesResolve.
					self.playItem(source = source, metadata = metadata, handle = handle)
					return

				downloadType = None
				downloadId = None
				if not link == None and not link == '':
					downer = downloader.Downloader(downloader.Downloader.TypeCache)
					path = downer.download(media = self.type, link = link, metadata = metadata, source = source, automatic = True)
					if path and not path == '':
						downloadType = downer.type()
						downloadId = downer.id()
						item['url'] = path

						time.sleep(3) # Allow a few seconds for the download to start. Otherwise the download was queued but not started and the file was not created yet.
						downer.refresh()

				interface.Loader.hide()
				self.playLocal(path = path, source = source, metadata = metadata, downloadType = downloadType, downloadId = downloadId)
			else:
				self.playItem(source = source, metadata = metadata)
		except:
			interface.Loader.hide()
			tools.Logger.error()

	def playItem(self, source, metadata = None, downloadType = None, downloadId = None, handle = None, handleMode = None):
		try:
			try:
				if metadata == None:
					metadata = control.window.getProperty(self.metaProperty)
					metadata = json.loads(metadata)

				year = metadata['year'] if 'year' in metadata else None
				season = metadata['season'] if 'season' in metadata else None
				episode = metadata['episode'] if 'episode' in metadata else None

				imdb = metadata['imdb'] if 'imdb' in metadata else None
				tvdb = metadata['tvdb'] if 'tvdb' in metadata else None

				title = tools.Media.titleUniversal(metadata = metadata)
			except:
				title = source['tvshowtitle'] if 'tvshowtitle' in source else source['title']
				metadata = None
				year = None
				season = None
				episode = None
				imdb = None
				tvdb = None

			next = []
			prev = []
			total = []
			for i in range(1,1000):
				try:
					u = control.infoLabel('ListItem(%s).FolderPath' % str(i))
					if u in total: raise Exception()
					total.append(u)
					u = dict(urlparse.parse_qsl(u.replace('?','')))
					u = json.loads(u['source'])[0]
					next.append(u)
				except:
					break
			for i in range(-1000,0)[::-1]:
				try:
					u = control.infoLabel('ListItem(%s).FolderPath' % str(i))
					if u in total: raise Exception()
					total.append(u)
					u = dict(urlparse.parse_qsl(u.replace('?','')))
					u = json.loads(u['source'])[0]
					prev.append(u)
				except:
					break

			try:
				item = source
				if isinstance(item, list):
					item = item[0]

				heading = interface.Translation.string(33451)
				message = interface.Format.fontBold(interface.Translation.string(33452))
				dots = ''
				label = message + ' ' + dots

				if handle == None and (not 'local' in item or not item['local']):
					handle = handler.Handler().serviceDetermine(mode = handleMode, item = item, popups = True)
					if handle == handler.Handler.ReturnUnavailable or handle == handler.Handler.ReturnExternal or handle == handler.Handler.ReturnCancel:
						interface.Loader.hide()
						return None

				background = tools.Settings.getInteger('interface.stream.progress') == 1
				progressDialog = interface.Dialog.progress(background = background, title = heading, message = label)
				if background: progressDialog.update(0, heading, label)
				else: progressDialog.update(0, label)

				block = None
				image = None
				if not metadata == None:
					keys = ['poster', 'poster1', 'poster2', 'poster3', 'thumb', 'thumb1', 'thumb2', 'thumb3', 'icon', 'icon1', 'icon2', 'icon3']
					for key in keys:
						if key in metadata:
							value = metadata[key]
							if not value == None and not value == '':
								image = value
								break

				#interface.Dialog.notification(title = heading, titleless = True, message = title, icon = image, time = 5000) # Notification can be shown above progress dialog.

				try:
					if progressDialog.iscanceled():
						interface.Loader.hide()
						return None
				except: pass

				if background: progressDialog.update(5, heading, label)
				else: progressDialog.update(5, label)

				try: local = item['local']
				except: local = False

				if item['source'] == block: raise Exception()
				self.tResolved = None

				# Torrents and usenet have a download dialog with their own thread. Do not start a thread for them here.
				if not local and (item['source'] == 'torrent' or item['source'] == 'usenet'):
					# Do not close the dialog, otherwise there is a period where no dialog is showing.
					# The progress dialog in the debrid downloader (through sourcesResolve), will overwrite this.
					#progressDialog.close()

					labelTransferring = 33674 if item['source'] == 'torrent' else 33675
					labelTransferring = interface.Format.fontBold(interface.Translation.string(labelTransferring))
					if background: progressDialog.update(10, heading, labelTransferring)
					else: progressDialog.update(10, labelTransferring)

					def _resolve(item, handle):
						debridx.PremiumizeInterface.stop()
						debridx.RealDebridInterface.stop()

						# Download the container. This is also done by sourcesResolve(), but download it here to show it to the user in the dialog, because it takes some time.
						try:
							pro = provider.Provider.provider(item['provider'].lower(), enabled = False, local = True)['object']
						except:
							# When playing a stream from History after the provider was disabled.
							provider.Provider.initialize(forceAll = True)
							pro = provider.Provider.provider(item['provider'].lower(), enabled = False, local = True)['object']

						link = item['url']
						try: link = pro.resolve(link, internal = internal)
						except: link = pro.resolve(link)
						network.Container(link = link, download = True).hash()

					thread = workers.Thread(_resolve, item, handle)
					thread.start()

					progress = 0
					while thread.is_alive():
						try:
							if xbmc.abortRequested == True:
								sys.exit()
								interface.Loader.hide()
								return None
							if progressDialog.iscanceled():
								progressDialog.close()
								interface.Loader.hide()
								return None
						except:
							interface.Loader.hide()

						dots += '.'
						if len(dots) > 3: dots = ''
						label = labelTransferring + ' ' + dots

						progress += 0.25
						progressCurrent = 5 + min(int(progress), 30)
						if background: progressDialog.update(progressCurrent, heading, label)
						else: progressDialog.update(progressCurrent, label)

						time.sleep(0.5)

					label = message
					if background: progressDialog.update(30, heading, labelTransferring)
					else: progressDialog.update(30, labelTransferring)

					self.tResolved = self.sourcesResolve(item, info = True, handle = handle, handleMode = handleMode, handleClose = False)

					if not self.url == None and not self.url == '':
						if background: progressDialog.update(45, heading, label)
						else: progressDialog.update(45, label)
				else:
					def _resolve(item, handle):
						self.tResolved = self.sourcesResolve(item, info = True, handle = handle, handleMode = handleMode, handleClose = False)

					w = workers.Thread(_resolve, item, handle)
					w.start()

					end = 3600
					for x in range(end):
						try:
							if xbmc.abortRequested == True:
								sys.exit()
								interface.Loader.hide()
								return None
							if progressDialog.iscanceled():
								progressDialog.close()
								interface.Loader.hide()
								return None
						except:
							interface.Loader.hide()

						if not control.condVisibility('Window.IsActive(virtualkeyboard)') and not control.condVisibility('Window.IsActive(yesnoDialog)'):
							break

						dots += '.'
						if len(dots) > 3: dots = ''
						label = message + ' ' + dots

						progress = 5 + int((x / float(end)) * 20)
						if background: progressDialog.update(progress, heading, label)
						else: progressDialog.update(progress, label)

						time.sleep(0.5)

					try: canceled = progressDialog.iscanceled()
					except: canceled = False
					if not canceled:
						end = 30
						for x in range(end):
							try:
								if xbmc.abortRequested == True:
									sys.exit()
									interface.Loader.hide()
									return None
								if progressDialog.iscanceled():
									progressDialog.close()
									interface.Loader.hide()
									return None
							except:
								interface.Loader.hide()

							if not w.is_alive(): break

							dots += '.'
							if len(dots) > 3: dots = ''
							label = message + ' ' + dots

							progress = 25 + int((x / float(end)) * 25)
							if background: progressDialog.update(progress, heading, label)
							else: progressDialog.update(progress, label)

							time.sleep(0.5)

						# For pairing dialogs to remain open.
						# Have it in two steps to have a smoother progress, instead of a very long single timeout.
						try: canceled = progressDialog.iscanceled()
						except: canceled = False
						if not canceled and w.is_alive():
							end = 3600
							for x in range(end):
								try:
									if xbmc.abortRequested == True:
										sys.exit()
										interface.Loader.hide()
										return None
									if progressDialog.iscanceled():
										progressDialog.close()
										interface.Loader.hide()
										return None
								except:
									interface.Loader.hide()

								if not w.is_alive(): break

								dots += '.'
								if len(dots) > 3: dots = ''
								label = message + ' ' + dots

								progress = 50
								if background: progressDialog.update(progress, heading, label)
								else: progressDialog.update(progress, label)

								time.sleep(0.5)

						if w.is_alive() == True:
							block = item['source']

				try: canceled = progressDialog.iscanceled()
				except: canceled = False
				if not canceled:
					if background: progressDialog.update(50, heading, label)
					else: progressDialog.update(50, label)

				item['urlresolved'] = self.tResolved
				if self.url == None or self.url == '':
					interface.Loader.hide() # Must be hidden here.
					return

				history.History().insert(type = self.type, kids = self.kids, link = item['url'], metadata = metadata, source = source)

				control.sleep(200)
				control.execute('Dialog.Close(virtualkeyboard)')
				control.execute('Dialog.Close(yesnoDialog)')

				# If the background dialog is not closed, when another background dialog is launched, it will contain the old information from the previous dialog.
				# Manually close it. Do not close the foreground dialog, since it does not have the issue and keeping the dialog shown is smoother transition.
				if background:
					progressDialog.update(100, '') # Must be set to 100, otherwise it shows up in a later dialog.
					progressDialog.close()
					interface.Loader.show() # Since there is no dialog anymore.

				from resources.lib.modules.player import player
				player().run(title, year, season, episode, imdb, tvdb, self.url, metadata, downloadType = downloadType, downloadId = downloadId, handle = handle, source = item)

				return self.url
			except:
				tools.Logger.error()
				interface.Loader.hide()

			try: progressDialog.close()
			except: pass

			self.errorForSources(single = True)
		except:
			tools.Logger.error()
			interface.Loader.hide()

	# Used by downloader.
	def playLocal(self, path, source, metadata, downloadType = None, downloadId = None):
		source['url'] = path
		source['local'] = True
		self.playItem(source = source, metadata = metadata, downloadType = downloadType, downloadId = downloadId)

	def getSources(self, title, year, imdb, tvdb, season, episode, tvshowtitle, premiered, meta = None, preset = None, seasoncount = None, exact = False, autoplay = False):
		try:
			def titleClean(value):
				if value == None: return None

				# Remove years in brackets from titles.
				# Do not remove years that are not between brackets, since it might be part of the title. Eg: 2001 A Space Oddesy
				# Eg: Heartland (CA) (2007) -> Heartland (CA)
				value = re.sub('\([0-9]{4}\)', '', value)
				value = re.sub('\[[0-9]{4}\]', '', value)
				value = re.sub('\{[0-9]{4}\}', '', value)

				# Remove symbols.
				# Eg: Heartland (CA) -> Heartland CA
				value = re.sub('[^A-Za-z0-9\s]', '', value)

				# Replace extra spaces.
				value = re.sub('\s\s+', ' ', value)
				value = value.strip()

				return value

			def isCancled():
				if background: return False
				else:
					try:
						if xbmc.abortRequested:
							sys.exit()
							return True
					except: pass
					try: return self.progressDialog.iscanceled()
					except: pass
					return False

			def update(percentage, message1, message2 = None, message2Alternative = None, showElapsed = True):
				if percentage == None: percentage = self.progressPercentage
				else: self.progressPercentage = max(percentage, self.progressPercentage) # Do not let the progress bar go back if more streams are added while precheck is running.

				if not message2: message2 = ''

				if background:
					if message2Alternative: message2 = message2Alternative
					# Do last, because of message2Alternative. Must be done BEFORE dialog update, otherwise stream count sometimes jumps back.
					self.mLastMessage1 = message1
					self.mLastMessage2 = message2
					elapsedTime = elapsed(False) + interface.Format.separator() if showElapsed else ''
					self.progressDialog.update(self.progressPercentage, name + message1, elapsedTime + message2)
				else:
					# Do last, because of message2Alternative. Must be done BEFORE dialog update, otherwise stream count sometimes jumps back.
					self.mLastMessage1 = message1
					self.mLastMessage2 = message2
					elapsedTime = elapsed(True) if showElapsed else ' '
					self.progressDialog.update(self.progressPercentage, message1, elapsedTime, message2)

			def updateTime():
				while not self.stopThreads:
					update(self.progressPercentage, self.mLastMessage1, self.mLastMessage2)
					time.sleep(0.2)

			def elapsed(description = True):
				seconds = max(0, timer.elapsed())
				if description: return timeStringDescription % seconds
				else: return timeString % seconds

			def additionalInformation(title, tvshowtitle, imdb, tvdb):
				threadsInformation = []

				threadsInformation.append(workers.Thread(additionalInformationTitle, title, tvshowtitle, imdb, tvdb))

				if not tvshowtitle == None: title = tvshowtitle
				threadsInformation.append(workers.Thread(additionalInformationCharacters, title, imdb, tvdb))

				[thread.start() for thread in threadsInformation]
				[thread.join() for thread in threadsInformation]

				# Title for the foreign language in the settings.
				if self.titleLocal:
					local = tools.Converter.unicode(self.titleLocal)
					if not local == tools.Converter.unicode(title):
						found = False
						for value in self.titleAlternatives.itervalues():
							if tools.Converter.unicode(value) == local:
								found = True
								break
						if not found:
							self.titleAlternatives['local'] = self.titleLocal

			def additionalInformationCharacters(title, imdb, tvdb):
				try:
					# NB: Always compare the unicode (tools.Converter.unicode) of the titles.
					# Some foreign titles have some special character at the end, which will cause titles that are actually the same not to be detected as the same.
					# Unicode function will remove unwanted characters. Still keep the special characters in the variable.

					if tools.Settings.getBoolean('accounts.informants.tmdb.enabled'):
						tmdbApi = tools.Settings.getString('accounts.informants.tmdb.api')
						if not tmdbApi == '':
							result = cache.get(client.request, 240, 'http://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id' % (imdb, tmdbApi))
							self.progressInformationCharacters = 25
							result = json.loads(result)
							if 'original_title' in result: # Movies
								self.titleOriginal = result['original_title']
							elif 'original_name' in result: # Shows
								self.titleOriginal = result['original_name']

					if not self.titleOriginal:
						self.progressInformationCharacters = 50
						result = cache.get(client.request, 240, 'http://www.imdb.com/title/%s' % (imdb))
						self.progressInformationCharacters = 75
						result = BeautifulSoup(result)
						resultTitle = result.find_all('div', class_ = 'originalTitle')
						if len(resultTitle) > 0:
							self.titleOriginal = resultTitle[0].getText()
							self.titleOriginal = self.titleOriginal[:self.titleOriginal.rfind('(')]
						else:
							resultTitle = result.find_all('h1', {'itemprop' : 'name'})
							if len(resultTitle) > 0:
								self.titleOriginal = resultTitle[0].getText()
								self.titleOriginal = self.titleOriginal[:self.titleOriginal.rfind('(')]

					try: # UTF-8 and ASCII comparison might fail
						self.titleOriginal = self.titleOriginal.strip() # Sometimes foreign titles have a space at the end.
						if tools.Converter.unicode(self.titleOriginal) == tools.Converter.unicode(title): # Do not search if they are the same.
							self.titleOriginal = None
					except: pass

					self.titleForeign1 = metadatax.Metadata.foreign(title)
					try: # UTF-8 and ASCII comparison might fail
						if any(i == tools.Converter.unicode(self.titleForeign1) for i in [tools.Converter.unicode(title), tools.Converter.unicode(self.titleOriginal)]):
							self.titleForeign1 = None
					except: pass

					if self.titleOriginal:
						self.titleForeign2 = metadatax.Metadata.foreign(self.titleOriginal)
						try: # UTF-8 and ASCII comparison might fail
							if any(i == tools.Converter.unicode(self.titleForeign2) for i in [tools.Converter.unicode(title), tools.Converter.unicode(self.titleOriginal), tools.Converter.unicode(self.titleForeign1)]):
								self.titleForeign2 = None
						except: pass

					self.titleUmlaut1 = metadatax.Metadata.foreign(title, True)
					try: # UTF-8 and ASCII comparison might fail
						if any(i == tools.Converter.unicode(self.titleUmlaut1) for i in [tools.Converter.unicode(title), tools.Converter.unicode(self.titleOriginal), tools.Converter.unicode(self.titleForeign1), tools.Converter.unicode(self.titleForeign2)]):
							self.titleUmlaut1 = None
					except: pass

					if self.titleOriginal:
						self.titleUmlaut2 = metadatax.Metadata.foreign(self.titleOriginal, True)
						try: # UTF-8 and ASCII comparison might fail
							if any(i == tools.Converter.unicode(self.titleUmlaut2) for i in [tools.Converter.unicode(title), tools.Converter.unicode(self.titleOriginal), tools.Converter.unicode(self.titleForeign1), tools.Converter.unicode(self.titleForeign2), tools.Converter.unicode(self.titleUmlaut1)]):
								self.titleUmlaut2 = None
						except: pass

					if not self.titleOriginal == None: self.titleAlternatives['original'] = self.titleOriginal
					if not self.titleForeign1 == None: self.titleAlternatives['foreign1'] = self.titleForeign1
					if not self.titleForeign2 == None: self.titleAlternatives['foreign2'] = self.titleForeign2
					if not self.titleUmlaut1 == None: self.titleAlternatives['umlaut1'] = self.titleUmlaut1
					if not self.titleUmlaut2 == None: self.titleAlternatives['umlaut2'] = self.titleUmlaut2

					# Also search titles that contain abbrviations (consecutive capital letters).
					# Eg: "K.C. Undercover" is retrieved as "KC Undercover" by informants. Most providers have it as "K C Undercover".
					self.titleAbbreviation = self.titleOriginal
					abbreviations = re.findall('[A-Z]{2,}', self.titleAbbreviation)

					if not self.titleAbbreviation == self.titleOriginal:
						self.titleAlternatives['abbreviation'] = self.titleAbbreviation

					self.progressInformationCharacters = 100
				except:
					pass

			def additionalInformationTitle(title, tvshowtitle, imdb, tvdb):
				self.progressInformationLanguage = 25
				if tvshowtitle == None:
					content = 'movie'
					title = cleantitle.normalize(title)
					self.titleLocal = self.getLocalTitle(title, imdb, tvdb, content)
					self.progressInformationLanguage = 50
					self.titleAliases = self.getAliasTitles(imdb, self.titleLocal, content)
				else:
					content = 'tvshow'
					tvshowtitle = cleantitle.normalize(tvshowtitle)
					self.titleLocal = self.getLocalTitle(tvshowtitle, imdb, tvdb, content)
					self.progressInformationLanguage = 50
					self.titleAliases = self.getAliasTitles(imdb, self.titleLocal, content)
				self.progressInformationLanguage = 100

			def initializeProviders(movie, preset, imdb, tvdb):
				if movie:
					content = 'movie'
					type = 'imdb'
					id = imdb
				else:
					content = 'show'
					type = 'tvdb'
					id = tvdb
				genres = trakt.getGenre(content, type, id)

				if not preset == None: provider.Provider.initialize(forcePreset = preset)
				if movie: self.providers = provider.Provider.providersMovies(enabled = True, local = True, genres = genres)
				else: self.providers = provider.Provider.providersTvshows(enabled = True, local = True, genres = genres)

			threads = []

			self.streamsHdUltra = 0
			self.streamsHd1080 = 0
			self.streamsHd720 = 0
			self.streamsSd = 0
			self.streamsScr = 0
			self.streamsCam = 0

			self.stopThreads = False
			self.threadsAdjusted = []
			self.sourcesAdjusted = []
			self.statusAdjusted = []
			self.cachedAdjusted = 0
			self.cachedAdjustedBusy = False
			self.priortityAdjusted = []
			self.threadsMutex = Lock()

			# Termination

			self.terminationMutex = Lock()
			self.terminationPrevious = 0
			self.terminationMode = tools.Settings.getInteger('scraping.termination.mode')
			self.terminationEnabled = tools.Settings.getBoolean('scraping.termination.enabled') and (self.terminationMode == 0 or (self.terminationMode == 1 and not autoplay) or (self.terminationMode == 2 and autoplay))
			self.terminationCount = tools.Settings.getInteger('scraping.termination.count')
			self.terminationType = tools.Settings.getInteger('scraping.termination.type')
			self.terminationVideoQuality = tools.Settings.getInteger('scraping.termination.video.quality')
			self.terminationVideoCodec = tools.Settings.getInteger('scraping.termination.video.codec')
			self.terminationAudioChannels = tools.Settings.getInteger('scraping.termination.audio.channels')
			self.terminationAudioCodec = tools.Settings.getInteger('scraping.termination.audio.codec')

			terminationTemporary = {}
			if self.terminationType in [1, 4, 5, 7]:
				terminationTemporary['premium'] = True
			if self.terminationType in [2, 4, 6, 7]:
				terminationTemporary['debridcache'] = True
			if self.terminationType in [3, 5, 6, 7]:
				terminationTemporary['direct'] = True
			self.terminationType = terminationTemporary
			self.terminationTypeHas = len(self.terminationType) > 0

			terminationTemporary = []
			if self.terminationVideoQuality > 0:
				for i in range(self.terminationVideoQuality - 1, len(metadatax.Metadata.VideoQualityOrder)):
					terminationTemporary.append(metadatax.Metadata.VideoQualityOrder[i])
			self.terminationVideoQuality = terminationTemporary
			self.terminationVideoQualityHas = len(self.terminationVideoQuality) > 0

			terminationTemporary = []
			if self.terminationVideoCodec > 0:
				if self.terminationVideoCodec in [1, 3]:
					terminationTemporary.append('H264')
				if self.terminationVideoCodec in [1, 2]:
					terminationTemporary.append('H265')
			self.terminationVideoCodec = terminationTemporary
			self.terminationVideoCodecHas = len(self.terminationVideoCodec) > 0

			terminationTemporary = []
			if self.terminationAudioChannels > 0:
				if self.terminationAudioChannels in [1, 2]:
					terminationTemporary.append('8CH')
				if self.terminationAudioChannels in [1, 3]:
					terminationTemporary.append('6CH')
				if self.terminationAudioChannels in [4]:
					terminationTemporary.append('2CH')
			self.terminationAudioChannels = terminationTemporary
			self.terminationAudioChannelsHas = len(self.terminationAudioChannels) > 0

			terminationTemporary = []
			if self.terminationAudioCodec > 0:
				if self.terminationAudioCodec in [1, 2, 3]:
					terminationTemporary.append('DTS')
				if self.terminationAudioCodec in [1, 2, 4]:
					terminationTemporary.append('DD')
				if self.terminationAudioCodec in [1, 5]:
					terminationTemporary.append('AAC')
			self.terminationAudioCodec = terminationTemporary
			self.terminationAudioCodecHas = len(self.terminationAudioCodec) > 0

			# Limit the number of running threads.
			# Can be more than actual core count, since threads in python are run on a single core.
			# Do not use too many, otherwise Kodi begins lagging (eg: the dialog is not updated very often, and the elapsed seconds are stuck).
			# NB: Do not use None (aka unlimited). If 500+ links are found, too many threads are started, causing a major delay by having to switch between threads. Use a limited number of threads.
			self.threadsLimit = tools.Hardware.processors() * 2

			control.makeFile(control.dataPath)
			self.sourceFile = control.providercacheFile

			self.titleLanguages = {}
			self.titleAlternatives = {}
			self.titleLocal = None
			self.titleAliases = []
			self.titleOriginal = None
			self.titleAbbreviation = None
			self.titleForeign1 = None
			self.titleForeign2 = None
			self.titleUmlaut1 = None
			self.titleUmlaut2 = None

			self.enabledDevelopers = tools.System.developers()
			self.enabledForeign = tools.Settings.getBoolean('scraping.foreign.enabled')
			self.enabledPrecheck = self.enabledDevelopers and tools.Settings.getBoolean('scraping.precheck.enabled')
			self.enabledMetadata = self.enabledDevelopers and tools.Settings.getBoolean('scraping.metadata.enabled')
			self.enabledCache = tools.Settings.getBoolean('scraping.cache.enabled') and debrid.statusPremiumize()
			self.enabledFailures = provider.Provider.failureEnabled()

			self.progressDialog = None
			self.progressInformationLanguage = 0
			self.progressInformationCharacters = 0
			self.progressPercentage = 0

			percentageDone = 0
			percentageInitialize = 0.05
			percentageForeign = 0.05 if self.enabledForeign else 0
			percentagePrecheck = 0.15 if self.enabledPrecheck else 0
			percentageMetadata = 0.15 if self.enabledMetadata else 0
			percentageCache = 0.05 if self.enabledCache else 0
			percentageFinalizingStreams = 0.03
			percentageSaveStreams = 0.02
			percentageProviders = 1 - percentageInitialize - percentageForeign - percentagePrecheck - percentageMetadata - percentageCache - percentageFinalizingStreams - percentageSaveStreams - 0.01 # Subtract 0.01 to keep the progress bar always a bit empty in case provided sources something like 123 of 123, even with threads still running.

			heading = 'Stream Search'
			name = interface.Dialog.title(extension = '')
			background = tools.Settings.getInteger('interface.stream.progress') == 1
			self.mLastMessage1 = ''
			self.mLastMessage2 = ''

			timer = tools.Time()
			timerSingle = tools.Time()
			timeStep = 0.5
			timeString = '%s ' + control.lang(32405).encode('utf-8')
			timeStringDescription = control.lang(32404).encode('utf-8') + ': ' + timeString

			message = interface.Format.fontBold('Initializing Providers')
			self.progressDialog = interface.Dialog.progress(background = background, title = heading, message = message)
			interface.Loader.hide()

			timer.start()
			# Ensures that the elapsed time in the dialog is updated more frequently.
			# Otherwise the update is laggy if many threads run.
			timeThread = workers.Thread(updateTime)
			timeThread.start()

			title = titleClean(title)
			tvshowtitle = titleClean(tvshowtitle)
			movie = tvshowtitle == None if self.type == None else (self.type == tools.Media.TypeMovie or self.type == self.type == tools.Media.TypeDocumentary or self.type == self.type == tools.Media.TypeShort)

			# Clear old sources from database.
			# Due to long links and metadata, the database entries can grow very large, not only wasting disk space, but also reducing search/insert times.
			# Delete old entries that will be ignored in any case.
			self.clearSourcesOld(wait = False)

			# Start the additional information before the providers are intialized.
			# Save some search time. Even if there are no providers available later, still do this.
			threadAdditional = None
			if not isCancled() and self.enabledForeign:
				threadAdditional = workers.Thread(additionalInformation, title, tvshowtitle, imdb, tvdb)
				threadAdditional.start()

			if not isCancled():
				timeout = 10
				message = interface.Format.fontBold('Initializing Providers')
				thread = workers.Thread(initializeProviders, movie, preset, imdb, tvdb)

				thread.start()
				timerSingle.start()
				while True:
					try:
						if isCancled(): break
						if not thread.is_alive(): break
						update(int((min(1, timerSingle.elapsed() / float(timeout))) * percentageInitialize * 100), message)
						time.sleep(timeStep)
					except:
						tools.Logger.error()
						pass
				del thread

			if len(self.providers) == 0 and not isCancled():
				interface.Dialog.notification(message = 'No Providers Available', icon = interface.Dialog.IconError)
				self.stopThreads = True
				time.sleep(0.3) # Ensure the time thread (0.2 interval) is stopped.
				return 'unavailable'
			elif isCancled():
				self.stopThreads = True
				time.sleep(0.3) # Ensure the time thread (0.2 interval) is stopped.
				return 'unavailable'

			update(int(percentageInitialize * 100), message) # In case the initialization finishes early.

			if not isCancled() and self.enabledForeign:
				percentageDone = percentageInitialize
				message = interface.Format.fontBold('Retrieving Additional Information')
				try: timeout = tools.Settings.getInteger('scraping.foreign.timeout')
				except: timeout = 15

				timerSingle.start()
				while True:
					try:
						if isCancled(): break
						if not threadAdditional.is_alive(): break
						update(int((((self.progressInformationLanguage + self.progressInformationCharacters) / 2.0) * percentageForeign) + percentageDone), message)
						time.sleep(timeStep)
						if timerSingle.elapsed() >= timeout: break
					except:
						tools.Logger.error()
						pass
				del threadAdditional

				if isCancled():
					self.stopThreads = True
					time.sleep(0.3) # Ensure the time thread (0.2 interval) is stopped.
					return 'unavailable'

			if movie:
				title = cleantitle.normalize(title)
				for source in self.providers:
					threads.append(workers.Thread(self.getMovieSourceAlternatives, self.titleAlternatives, title, self.titleLocal, self.titleAliases, year, imdb, source, exact)) # Only language title for the first thread.
			else:
				tvshowtitle = cleantitle.normalize(tvshowtitle)
				for source in self.providers:
					threads.append(workers.Thread(self.getEpisodeSourceAlternatives, self.titleAlternatives, title, self.titleLocal, self.titleAliases, year, imdb, tvdb, season, episode, seasoncount, tvshowtitle, premiered, source, exact)) # Only language title for the first thread.

			sourceLabel = [i['name'] for i in self.providers]
			[i.start() for i in threads]

			# Finding Sources
			if not isCancled():
				percentageDone = percentageForeign + percentageInitialize
				message = interface.Format.fontBold('Finding Stream Sources')
				stringInput1 = 'Processed Providers: %d of %d'
				stringInput2 = 'Providers: %d of %d'
				stringInput3 = interface.Format.newline() + 'Found Streams: %d'
				try: timeout = tools.Settings.getInteger('scraping.providers.timeout')
				except: timeout = 30
				termination = 0
				timerSingle.start()

				while True:
					try:
						if isCancled() or timerSingle.elapsed() >= timeout:
							break

						termination += 1
						if termination >= 4: # Every 2 secs.
							termination = 0
							if self.adjustTermination():
								break

						totalThreads = len(threads)
						info = []
						for x in range(totalThreads):
							if threads[x].is_alive():
								info.append(sourceLabel[x])
						aliveCount = len([x for x in threads if x.is_alive()])
						doneCount = totalThreads - len(info)

						if aliveCount == 0:
							break

						foundStreams = []
						if len(foundStreams) < 2 and self.streamsHdUltra > 0: foundStreams.append('%sx HDULTRA' % self.streamsHdUltra)
						if len(foundStreams) < 2 and self.streamsHd1080 > 0: foundStreams.append('%sx HD1080' % self.streamsHd1080)
						if len(foundStreams) < 2 and self.streamsHd720 > 0: foundStreams.append('%sx HD720' % self.streamsHd720)
						if len(foundStreams) < 2 and self.streamsSd > 0: foundStreams.append('%sx SD' % self.streamsSd)
						if len(foundStreams) < 2 and self.streamsScr > 0: foundStreams.append('%sx SCR' % self.streamsScr)
						if len(foundStreams) < 2 and self.streamsCam > 0: foundStreams.append('%sx CAM' % self.streamsCam)
						if len(foundStreams) > 0: foundStreams = ' [%s]' % (', '.join(foundStreams))
						else: foundStreams = ''

						percentage = int((((doneCount / float(totalThreads)) * percentageProviders) + percentageDone) * 100)
						stringProvidersValue1 = stringInput1 % (doneCount, totalThreads)
						stringProvidersValue2 = stringInput2 % (doneCount, totalThreads)
						if len(info) <= 2: stringProvidersValue1 += ' [%s]' % (', '.join(info))
						stringProvidersValue1 += (stringInput3 % len(self.sourcesAdjusted)) + foundStreams
						update(percentage, message, stringProvidersValue1, stringProvidersValue2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break

			# Special handle for cancel on scraping. Allows to still inspect debrid cache after cancellation.
			specialAllow = False
			if isCancled():
				specialAllow = True
				self.progressDialog.close()
				time.sleep(0.2) # Must wait. Otherwise the canel interferes with the open.
				percentageDone = percentageForeign + percentageProviders + percentageInitialize
				message = interface.Format.fontBold('Stopping Stream Collection')
				self.progressDialog = interface.Dialog.progress(background = background, title = heading, message = message)
				update(percentageDone, message, ' ', ' ')

			# Failures
			# Do not detect failures if the scraping was canceled.
			if not isCancled() and self.enabledFailures:
				update(None, interface.Format.fontBold('Detecting Provider Failures'), ' ', ' ')
				threadsFinished = []
				threadsUnfinished = []
				for i in range(len(threads)):
					id = self.providers[i]['id']
					if threads[i].is_alive():
						threadsUnfinished.append(id)
					else:
						threadsFinished.append(id)
				provider.Provider.failureUpdate(finished = threadsFinished, unfinished = threadsUnfinished)

			del threads[:] # Make sure all providers are stopped.

			# Prechecks
			if (specialAllow or not isCancled()) and self.enabledPrecheck:
				percentageDone = percentageForeign + percentageProviders + percentageInitialize
				message = interface.Format.fontBold('Checking Stream Availability')
				stringInput1 = 'Processed Streams: %d of %d'
				stringInput2 = 'Streams: %d of %d'
				try: timeout = tools.Settings.getInteger('scraping.precheck.timeout')
				except: timeout = 30
				timerSingle.start()

				while True:
					try:
						if isCancled():
							specialAllow = False
							break
						if timerSingle.elapsed() >= timeout:
							break

						totalThreads = self.cachedAdjusted + len(self.threadsAdjusted)
						aliveCount = len([x for x in self.threadsAdjusted if x.is_alive()])
						doneCount = self.cachedAdjusted + len([x for x in self.statusAdjusted if x == 'done'])

						if aliveCount == 0:
							break

						percentage = int((((doneCount / float(totalThreads)) * percentagePrecheck) + percentageDone) * 100)
						stringSourcesValue1 = stringInput1 % (doneCount, totalThreads)
						stringSourcesValue2 = stringInput2 % (doneCount, totalThreads)
						update(percentage, message, stringSourcesValue1, stringSourcesValue2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break

			# Metadata
			if (specialAllow or not isCancled()) and self.enabledMetadata:
				percentageDone = percentagePrecheck + percentageForeign + percentageProviders + percentageInitialize
				message = interface.Format.fontBold('Retrieving Additional Metadata')
				stringInput1 = 'Processed Streams: %d of %d'
				stringInput2 = 'Streams: %d of %d'
				try: timeout = tools.Settings.getInteger('scraping.metadata.timeout')
				except: timeout = 30
				timerSingle.start()

				while True:
					try:
						if isCancled():
							specialAllow = False
							break
						if timerSingle.elapsed() >= timeout:
							break

						totalThreads = self.cachedAdjusted + len(self.threadsAdjusted)
						aliveCount = len([x for x in self.threadsAdjusted if x.is_alive()])
						doneCount = self.cachedAdjusted + len([x for x in self.statusAdjusted if x == 'done'])

						if aliveCount == 0:
							break

						percentage = int((((doneCount / float(totalThreads)) * percentageMetadata) + percentageDone) * 100)
						stringSourcesValue1 = stringInput1 % (doneCount, totalThreads)
						stringSourcesValue2 = stringInput2 % (doneCount, totalThreads)
						update(percentage, message, stringSourcesValue1, stringSourcesValue2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break

			# Finalizing Providers
			# Wait for all the source threads to complete.
			# This is especially important if there are not prechecks, metadata, or debrid cache inspection, and a provider finishes with a lot of streams just before the timeout.

			if specialAllow or not isCancled():
				percentageDone = percentageMetadata + percentagePrecheck + percentageForeign + percentageProviders + percentageInitialize
				message = interface.Format.fontBold('Finalizing Streams')
				stringInput1 = 'Processed Streams: %d of %d'
				stringInput2 = 'Streams: %d of %d'
				timeout = 60 # Can take some while for a lot of streams.
				timerSingle.start()

				while True:
					try:
						elapsedTime = timerSingle.elapsed()
						if isCancled() or elapsedTime >= timeout:
							break

						totalThreads = self.cachedAdjusted + len(self.threadsAdjusted)
						aliveCount = len([x for x in self.threadsAdjusted if x.is_alive()])
						doneCount = self.cachedAdjusted + len([x for x in self.statusAdjusted if x == 'done'])

						if aliveCount == 0:
							break

						percentage = int((((elapsedTime / float(timeout)) * percentageFinalizingStreams) + percentageDone) * 100)
						stringSourcesValue1 = stringInput1 % (doneCount, totalThreads)
						stringSourcesValue2 = stringInput2 % (doneCount, totalThreads)
						update(percentage, message, stringSourcesValue1, stringSourcesValue2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break

			# Debrid Cache
			premiumize = debridx.Premiumize().accountValid() and (tools.Settings.getBoolean('streaming.torrent.premiumize.enabled') or tools.Settings.getBoolean('streaming.usenet.premiumize.enabled'))
			if (specialAllow or not isCancled()) and self.enabledCache and premiumize:
				percentageDone = percentageFinalizingStreams + percentageMetadata + percentagePrecheck + percentageForeign + percentageProviders + percentageInitialize
				message = interface.Format.fontBold('Inspecting Debrid Cache')
				stringInput1 = ' ' # Must have space to remove line.
				stringInput2 = 'Inspecting Debrid Cache'
				try: timeout = tools.Settings.getInteger('scraping.cache.timeout')
				except: timeout = 30
				timerSingle.start()

				thread = workers.Thread(self.adjustSourceCache, timeout, False)
				thread.start()
				while True:
					try:
						elapsedTime = timerSingle.elapsed()
						if isCancled():
							specialAllow = False
							break
						if elapsedTime >= timeout:
							break
						if not thread.is_alive():
							break

						percentage = int((((elapsedTime / float(timeout)) * percentageCache) + percentageDone) * 100)
						update(percentage, message, stringInput1, stringInput2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break
				del thread

			# Finalizing Streams

			percentageDone = percentageFinalizingStreams + percentageMetadata + percentagePrecheck + percentageForeign + percentageProviders + percentageCache + percentageInitialize
			message = interface.Format.fontBold('Saving Streams')
			stringInput1 = ' ' # Must have space to remove line.
			stringInput2 = 'Saving Streams'
			timeout = 15
			timerSingle.start()

			thread = workers.Thread(self.adjustSourceDatabase) # Update Database
			thread.start()

			if not isCancled(): # The thread is still running in the background, even if the dialog was canceled previously.
				while True:
					try:
						elapsedTime = timerSingle.elapsed()
						if not thread.is_alive():
							break
						if isCancled() or elapsedTime >= timeout:
							break

						percentage = int((((elapsedTime / float(timeout)) * percentageSaveStreams) + percentageDone) * 100)
						update(percentage, message, stringInput1, stringInput2)

						time.sleep(timeStep)
					except:
						tools.Logger.error()
						break

			# Sources
			self.providers = []

			self.sources = self.sourcesAdjusted

			for i in range(len(self.sources)):
				self.sources[i]['kids'] = self.kids
				self.sources[i]['type'] = self.type

			self.stopThreads = True
			time.sleep(0.3) # Ensure the time thread (0.2 interval) is stopped.

			del self.threadsAdjusted[:] # Make sure all adjustments are stopped.
			self.sourcesAdjusted = [] # Do not delete, since the pointers are in self.sources now.

			# Postprocessing

			update(100, interface.Format.fontBold('Preparing Streams'), ' ', ' ', showElapsed = False)

			# Clear because member variable.
			self.threadsAdjusted = []
			self.sourcesAdjusted = []
			self.statusAdjusted = []
			self.priortityAdjusted = []

			return self.sources
		except:
			tools.Logger.error()
			return 'unavailable'

	def getMovieSourceAlternatives(self, alternativetitles, title, localtitle, aliases, year, imdb, source, exact):
		threads = []
		threads.append(workers.Thread(self.getMovieSource, title, localtitle, aliases, year, imdb, source, exact))
		for key, value in alternativetitles.iteritems():
			threads.append(workers.Thread(self.getMovieSource, value, localtitle, aliases, year, imdb, source, exact, key))
		[thread.start() for thread in threads]
		[thread.join() for thread in threads]

	def getMovieSource(self, title, localtitle, aliases, year, imdb, source, exact, mode = None):
		try:
			# Replace symbols with spaces. Eg: K.C. Undercover
			title = re.sub('\s{2,}', ' ', re.sub('[^a-zA-Z\d\s:]', ' ', title)).strip()

			if localtitle == None: localtitle = title
			if mode == None: mode = ''
			sourceId = source['id']
			sourceObject = source['object']
			sourceType = source['type']
			sourceName = source['name']
		except:
			pass

		try:
			# NB: Very often the execution on the databases throws an exception if multiple threads access the database at the same time.
			# NB: An OperationalError "database is locked" is thrown. Set a timeout to give the connection a few seconds to retry.
			# NB: 10 seconds is often not enough if there are a lot of providers locking the database.
			dbcon = database.connect(self.sourceFile, timeout = 30)
			dbcur = dbcon.cursor()
			dbcur.execute("CREATE TABLE IF NOT EXISTS links (""source TEXT, ""mode TEXT, ""imdb TEXT, ""season TEXT, ""episode TEXT, ""link TEXT, ""UNIQUE(source, mode, imdb, season, episode)"");")
			dbcur.execute("CREATE TABLE IF NOT EXISTS sources (""source TEXT, ""mode TEXT, ""imdb TEXT, ""season TEXT, ""episode TEXT, ""hosts TEXT, ""time INT, ""UNIQUE(source, mode, imdb, season, episode)"");")
		except:
			pass

		try:
			if not sourceType == provider.Provider.TypeLocal:
				sources = []
				dbcur.execute("SELECT * FROM sources WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, '', ''))
				match = dbcur.fetchone()
				t1 = int(match[6])
				t2 = tools.Time.timestamp()
				update = abs(t2 - t1) > 7200
				if update == False:
					sources = json.loads(match[5])
					self.addSources(sources, False)
					return sources
		except:
			pass

		try:
			url = None
			dbcur.execute("SELECT * FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, '', ''))
			url = dbcur.fetchone()
			url = url[5]
		except:
			pass

		try:
			if url == None:
				try: url = sourceObject.movie(imdb, title, localtitle, year)
				except: url = sourceObject.movie(imdb, title, localtitle, aliases, year)
				if exact:
					try: url += '&exact=1'
					except: pass
				if url == None: raise Exception()
				dbcur.execute("DELETE FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, '', ''))
				dbcur.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?, ?)", (sourceId, mode, imdb, '', '', url))
				dbcon.commit()
		except:
			pass

		try:
			sources = []
			sources = sourceObject.sources(url, self.hostDict, self.hostprDict)

			# In case the first domain fails, try the other ones in the domains list.
			if tools.System.developers() and tools.Settings.getBoolean('scraping.mirrors.enabled'):
				if (not sources or len(sources) == 0) and hasattr(sourceObject, 'domains') and hasattr(sourceObject, 'base_link'):
					checked = [sourceObject.base_link.replace('http://', '').replace('https://', '')]
					for domain in sourceObject.domains:
						if not domain in checked:
							if not domain.startswith('http'):
								domain = 'http://' + domain
							sourceObject.base_link = domain
							checked.append(domain.replace('http://', '').replace('https://', ''))
							sources = sourceObject.sources(url, self.hostDict, self.hostprDict)
							if len(sources) > 0:
								break

			if sources == None or sources == []:
				# Insert an empty list to avoid the provider being executed again if scraped multiple times.
				timestamp = tools.Time.timestamp()
				data = json.dumps([])
				dbcur.execute("DELETE FROM sources WHERE source = '%s' AND mode = '%s' AND imdb = '%s'" % (sourceId, mode, imdb))
				dbcur.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)", (sourceId, mode, imdb, '', '', data, timestamp))
				dbcon.commit()
				raise Exception()

			try: title = '%s (%s)' % (title, year)
			except: pass

			for i in range(len(sources)):
				# Add title which will be used by sourcesResolve()
				sources[i]['title'] = title

				# Add provider to dictionary
				sources[i]['provider'] = sourceName

				# Change language
				sources[i]['language'] = sources[i]['language'].lower()

				# Update Google
				sources[i]['source'] = self.adjustRename(sources[i]['source'])

				# Exact
				sources[i]['exact'] = exact

			databaseCache = {'source' : sourceId, 'mode' : mode, 'imdb' : imdb, 'season' : '', 'episode' : ''}
			for i in range(len(sources)):
				sources[i]['database'] = copy.deepcopy(databaseCache)
			self.addSources(sources, True)
		except:
			pass

	def getEpisodeSourceAlternatives(self, alternativetitles, title, localtitle, aliases, year, imdb, tvdb, season, episode, seasoncount, tvshowtitle, premiered, source, exact):
		threads = []
		threads.append(workers.Thread(self.getEpisodeSource, title, localtitle, aliases, year, imdb, tvdb, season, episode, seasoncount, tvshowtitle, premiered, source, exact))
		for key, value in alternativetitles.iteritems():
			threads.append(workers.Thread(self.getEpisodeSource, title, localtitle, aliases, year, imdb, tvdb, season, episode, seasoncount, value, premiered, source, exact, key))
		[thread.start() for thread in threads]
		[thread.join() for thread in threads]

	def getEpisodeSource(self, title, localtitle, aliases, year, imdb, tvdb, season, episode, seasoncount, tvshowtitle, premiered, source, exact, mode = None):
		try:
			# Replace symbols with spaces. Eg: K.C. Undercover
			title = re.sub('\s{2,}', ' ', re.sub('[^a-zA-Z\d\s:]', ' ', title)).strip()
			tvshowtitle = re.sub('\s{2,}', ' ', re.sub('[^a-zA-Z\d\s:]', ' ', tvshowtitle)).strip()

			if localtitle == None: localtitle = title
			if mode == None: mode = ''
			sourceId = source['id']
			sourceObject = source['object']
			sourceType = source['type']
			sourceName = source['name']
		except:
			pass

		try:
			# NB: Very often the execution on the databases throws an exception if multiple threads access the database at the same time.
			# NB: An OperationalError "database is locked" is thrown. Set a timeout to give the connection a few seconds to retry.
			# NB: 10 seconds is often not enough if there are a lot of providers locking the database.
			dbcon = database.connect(self.sourceFile, timeout = 30)
			dbcur = dbcon.cursor()
			dbcur.execute("CREATE TABLE IF NOT EXISTS links (""source TEXT, ""mode TEXT, ""imdb TEXT, ""season TEXT, ""episode TEXT, ""link TEXT, ""UNIQUE(source, mode, imdb, season, episode)"");")
			dbcur.execute("CREATE TABLE IF NOT EXISTS sources (""source TEXT, ""mode TEXT, ""imdb TEXT, ""season TEXT, ""episode TEXT, ""hosts TEXT, ""time INT, ""UNIQUE(source, mode, imdb, season, episode)"");")
		except:
			pass

		try:
			if not sourceType == provider.Provider.TypeLocal:
				sources = []
				dbcur.execute("SELECT * FROM sources WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, season, episode))
				match = dbcur.fetchone()
				t1 = int(match[6])
				t2 = tools.Time.timestamp()
				update = abs(t2 - t1) > 7200
				if update == False:
					sources = json.loads(match[5])
					self.addSources(sources, False)
					return sources
		except:
			pass

		try:
			url = None
			dbcur.execute("SELECT * FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, '', ''))
			url = dbcur.fetchone()
			url = url[5]
		except:
			pass

		try:
			if url == None:
				try: url = sourceObject.tvshow(imdb, tvdb, tvshowtitle, localtitle, year)
				except: url = sourceObject.tvshow(imdb, tvdb, tvshowtitle, localtitle, aliases, year)
				if exact:
					try: url += '&exact=1'
					except: pass
				if url == None: raise Exception()
				dbcur.execute("DELETE FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, '', ''))
				dbcur.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?, ?)", (sourceId, mode, imdb, '', '', url))
				dbcon.commit()
		except:
			pass

		try:
			ep_url = None
			dbcur.execute("SELECT * FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, season, episode))
			ep_url = dbcur.fetchone()
			ep_url = ep_url[5]
		except:
			pass

		try:
			if url == None: raise Exception()
			if ep_url == None: ep_url = sourceObject.episode(url, imdb, tvdb, title, premiered, season, episode)
			if ep_url == None: raise Exception()
			dbcur.execute("DELETE FROM links WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, season, episode))
			dbcur.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?, ?)", (sourceId, mode, imdb, season, episode, ep_url))
			dbcon.commit()
		except:
			pass

		try:
			def _getEpisodeSource(url, mode, sourceId, sourceObject, sourceName, tvshowtitle, season, episode, imdb, currentSources, pack, packcount, exact):
				try:
					sources = []
					sources = sourceObject.sources(url, self.hostDict, self.hostprDict)

					# In case the first domain fails, try the other ones in the domains list.
					if tools.System.developers() and tools.Settings.getBoolean('scraping.mirrors.enabled'):
						if (not sources or len(sources) == 0) and hasattr(sourceObject, 'domains') and hasattr(sourceObject, 'base_link'):
							checked = [sourceObject.base_link.replace('http://', '').replace('https://', '')]
							for domain in sourceObject.domains:
								if not domain in checked:
									if not domain.startswith('http'):
										domain = 'http://' + domain
									sourceObject.base_link = domain
									checked.append(domain.replace('http://', '').replace('https://', ''))
									sources = sourceObject.sources(url, self.hostDict, self.hostprDict)
									if len(sources) > 0:
										break

					if sources == None or sources == []:
						# Insert an empty list to avoid the provider being executed again if scraped multiple times.
						timestamp = tools.Time.timestamp()
						data = json.dumps([])
						dbcur.execute("DELETE FROM sources WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (sourceId, mode, imdb, season, episode))
						dbcur.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)", (sourceId, mode, imdb, season, episode, data, timestamp))
						dbcon.commit()
						raise Exception()

					try: title = '%s S%02dE%02d' % (tvshowtitle, int(season), int(episode))
					except: title = tvshowtitle

					for i in range(len(sources)):
						# Add title which will be used by sourceResolve()
						sources[i]['title'] = title

						# Set season pack
						sources[i]['pack'] = pack
						if packcount: sources[i]['packcount'] = packcount

						# Add provider to dictionary
						sources[i]['provider'] = sourceName

						# Change language
						sources[i]['language'] = sources[i]['language'].lower()

						# Update Google
						sources[i]['source'] = self.adjustRename(sources[i]['source'])

						# Exact
						sources[i]['exact'] = exact

					databaseCache = {'source' : sourceId, 'mode' : mode, 'imdb' : imdb, 'season' : season, 'episode' : episode}
					for i in range(len(sources)):
						sources[i]['database'] = copy.deepcopy(databaseCache)

					self.addSources(sources, True)
				except:
					pass
				return sources

			# Get normal episodes
			currentSources = []
			currentSources += _getEpisodeSource(ep_url, mode, sourceId, sourceObject, sourceName, tvshowtitle, season, episode, imdb, currentSources, False, seasoncount, exact)

			# Get season packs
			if tools.Settings.getBoolean('scraping.packs.enabled') and source['pack']:
				se_url = urlparse.parse_qs(ep_url)
				se_url = dict([(i, se_url[i][0]) if se_url[i] else (i, '') for i in se_url])
				se_url['pack'] = True
				if seasoncount: se_url['packcount'] = seasoncount
				se_url = urllib.urlencode(se_url)
				_getEpisodeSource(se_url, mode, sourceId, sourceObject, sourceName, tvshowtitle, season, episode, imdb, currentSources, True, seasoncount, exact)

		except:
			pass

	def addSources(self, sources, check):
		if self.stopThreads:
			return
		try:
			if len(sources) > 0:
				enabled = tools.Settings.getBoolean('scraping.precheck.enabled') or tools.Settings.getBoolean('scraping.metadata.enabled') or tools.Settings.getBoolean('scraping.cache.enabled')
				self.sources.extend(sources)
				for source in sources:
					source['source'] = sourceName = source['source'].strip().lower().replace('www.', '')

					for i in self.debridDict.itervalues():
						found = False
						for j in i:
							if j in sourceName or sourceName in j:
								found = True
								source['debrid'] = True
								break
						if found: break
					if not 'debrid' in source:
						source['debrid'] = False

					quality = metadatax.Metadata.videoQualityConvert(source['quality'])
					source['quality'] = quality
					metadata = metadatax.Metadata.initialize(source)
					metadata.update(source)
					source['metadata'] = metadata
					index = self.adjustSourceAppend(source)
					if index < 0: continue

					priority = False
					if 'K' in quality:
						priority = True
						self.streamsHdUltra += 1 # 4K or higher
					elif quality == 'HD1080':
						priority = True
						self.streamsHd1080 += 1
					elif quality == 'HD720':
						priority = True
						self.streamsHd720 += 1
					elif quality == 'SD': self.streamsSd += 1
					elif 'SCR' in quality: self.streamsScr += 1
					elif 'CAM' in quality: self.streamsCam += 1

					if check and enabled:
						thread = workers.Thread(self.adjustSource, source, index)
						self.priortityAdjusted.append(priority) # Give priority to HD links
						self.statusAdjusted.append('queued')
						self.threadsAdjusted.append(thread)
					else:
						self.cachedAdjusted += 1
				self.adjustSourceStart()

				thread = workers.Thread(self.adjustSourceCache, None, True)
				thread.start()
		except:
			tools.Logger.error()

	def adjustRename(self, source):
		name = source.lower()
		if 'gvideo' in name or ('google' in name and 'vid' in name):
			source = 'GoogleVideo'
		elif 'google' in name and 'doc' in name:
			source = 'GoogleDocs'
		elif 'google' in name and 'drive' in name:
			source = 'GoogleDrive'
		return source

	def adjustLock(self):
		# NB: For some reason Python somtimes throws an exception saying that a unlocked/locked lock (tried) to aquire/release. Always keep these statements in a try-catch.
		try: self.threadsMutex.acquire()
		except: pass

	def adjustUnlock(self):
		# NB: For some reason Python somtimes throws an exception saying that a unlocked/locked lock (tried) to aquire/release. Always keep these statements in a try-catch.
		try: self.threadsMutex.release()
		except: pass

	def adjustTerminationLock(self):
		try: self.terminationMutex.acquire()
		except: pass

	def adjustTerminationUnlock(self):
		try: self.terminationMutex.release()
		except: pass

	def adjustTermination(self):
		try:
			self.adjustTerminationLock()
			if self.terminationEnabled:
				self.adjustLock()

				# No new streams.
				if self.terminationPrevious == len(self.sourcesAdjusted):
					return
				self.terminationPrevious = len(self.sourcesAdjusted)

				counter = 0
				for i in range(len(self.sourcesAdjusted)):
					source = self.sourcesAdjusted[i]
					metadata = source['metadata']

					# Type
					if self.terminationTypeHas:
						found = False
						for key, value in self.terminationType.iteritems():
							if key in source and source[key] == value:
								found = True
								break
						if not found: continue

					# Video Quality
					if self.terminationVideoQualityHas:
						if not source['quality'] in self.terminationVideoQuality:
							continue

					# Video Codec
					if self.terminationVideoCodecHas:
						videoCodec = metadata.videoCodec()
						if not any([videoCodec == i for i in self.terminationVideoCodec]):
							continue

					# Audio Channels
					if self.terminationAudioChannelsHas:
						audioChannels = metadata.audioChannels()
						if not any([audioChannels == i for i in self.terminationAudioChannels]):
							continue

					# Audio Codec
					if self.terminationAudioCodecHas:
						audioCodec = metadata.audioCodec()
						if not any([audioCodec == i for i in self.terminationAudioCodec]):
							continue

					counter += 1
					if counter >= self.terminationCount:
						return True
		except:
			tools.Logger.error()
		finally:
			try: self.adjustTerminationUnlock()
			except: pass
			try: self.adjustUnlock()
			except: pass
		return False

	def adjustSourceCache(self, timeout = None, partial = False):
		# Premiumize seems to take long to verify usenet hashes.
		# Split torrents and usenet up, with the hope that torrents will complete, even when usenet takes very long.
		# Can also be due to expensive local hash calculation for NZBs.
		premiumize = debridx.Premiumize().accountValid() and (tools.Settings.getBoolean('streaming.torrent.premiumize.enabled') or tools.Settings.getBoolean('streaming.usenet.premiumize.enabled'))
		if tools.Settings.getBoolean('scraping.cache.enabled') and premiumize:
			if partial: # If it is the final full inspection, always execute, even if another partial inspection is still busy.
				self.adjustLock()
				busy = self.cachedAdjustedBusy
				self.adjustUnlock()
				if busy: return

			if timeout == None:
				try: timeout = tools.Settings.getInteger('scraping.cache.timeout')
				except: timeout = 30

			threads = []
			threads.append(workers.Thread(self._adjustSourceCache, 'torrent', timeout, partial))
			if tools.Settings.getBoolean('scraping.cache.preload.usenet'):
				threads.append(workers.Thread(self._adjustSourceCache, 'usenet', timeout, partial))

			self.adjustLock()
			self.cachedAdjustedBusy = True
			self.adjustUnlock()

			[thread.start() for thread in threads]
			[thread.join() for thread in threads]

			self.adjustLock()
			self.cachedAdjustedBusy = False
			self.adjustUnlock()

	def _adjustSourceCache(self, type, timeout, partial = False):
		try:
			self.adjustLock()
			hashes = []
			for source in self.sourcesAdjusted:
				if source['source'] == type:
					# Only check those that were not previously inspected.
					if not 'debridcache' in source or source['debridcache'] == None:
						# NB: Do not calculate the hash if it is not available.
						# The hash is not available because the NZB could not be downloaded, or is still busy in the thread.
						# Calling container.hash() will cause the NZB to download again, which causes long delays.
						# Since the hashes are accumlated here sequentially, it might cause the download to take so long that the actual debrid cache query has never time to execute.
						# If the NZBs' hashes are not available at this stage, ignore it.
						'''if not 'hash' in source:
							container = network.Container(link = source['url'])
							source['hash'] = container.hash()'''
						if 'hash' in source and not source['hash'] == None and not source['hash'] == '':
							hashes.append(source['hash'])
			self.adjustUnlock()

			# Partial will inspect the cache will the scraping is still busy.
			# Only check if there are a bunch of them, otherwise there are too many API calls (heavy load on both Premiumize and local machine).
			if partial and len(hashes) < 50:
				return

			if len(hashes) == 0:
				return

			caches = debridx.Premiumize().cached(id = hashes, timeout = timeout)

			# First filter out only those that are cached. Makes search faster.
			cachesYes = {}
			for cache in caches:
				if cache['cached']:
					cachesYes[cache['hash'].lower()] = True

			self.adjustLock()
			for i in range(len(self.sourcesAdjusted)):
				source = self.sourcesAdjusted[i]
				try:
					hash = source['hash'].lower() # Will raise an exception if not found.
					cache = cachesYes[hash]
					self.sourcesAdjusted[i]['debridcache'] = True
					del cachesYes[hash] # Remove found caches to make search faster.
					if len(cachesYes) == 0:
						break
				except:
					if not 'debridcache' in source:
						self.sourcesAdjusted[i]['debridcache'] = False
		except:
			tools.Logger.error()
		finally:
			try: self.adjustUnlock()
			except: pass

	# priority starts stream checks HD720 and greater first.
	def adjustSourceStart(self, priority = True):
		if self.stopThreads:
			return
		try:
			self.adjustLock()

			# HD links
			running = [i for i in self.threadsAdjusted if i.is_alive()]
			openSlots = None if self.threadsLimit == None else max(0, self.threadsLimit - len(running))
			counter = 0
			for j in range(len(self.threadsAdjusted)):
				if self.priortityAdjusted == True and self.statusAdjusted[j] == 'queued':
					self.statusAdjusted[j] = 'busy'
					self.threadsAdjusted[j].start()
					counter += 1
					if not openSlots == None and counter > openSlots:
						raise Exception('Maximum thread limit reached.')

			# Non-HD links
			running = [i for i in self.threadsAdjusted if i.is_alive()]
			openSlots = None if self.threadsLimit == None else max(0, self.threadsLimit - len(running))
			counter = 0
			for j in range(len(self.threadsAdjusted)):
				if self.statusAdjusted[j] == 'queued':
					self.statusAdjusted[j] = 'busy'
					self.threadsAdjusted[j].start()
					counter += 1
					if not openSlots == None and counter > openSlots:
						raise Exception('Maximum thread limit reached.')
		except:
			pass
		finally:
			try: self.adjustUnlock()
			except: pass

	def adjustSourceAppend(self, sourceOrSources):
		if self.stopThreads:
			return

		index = -1
		self.adjustLock()
		try:
			if isinstance(sourceOrSources, dict):
				if not self.adjustSourceContains(sourceOrSources, mutex = False):
					self.sourcesAdjusted.append(sourceOrSources)
					index = len(self.sourcesAdjusted) - 1
			else:
				for source in sourceOrSources:
					if not self.adjustSourceContains(source, mutex = False):
						self.sourcesAdjusted.append(source)
						index = len(self.sourcesAdjusted) - 1
		except:
			pass
		finally:
			try: self.adjustUnlock()
			except: pass
		return index

	def adjustSourceContains(self, source, mutex = True): # Filter out duplicate URLs early on, to reduce the prechecks & metadata on them.
		if self.stopThreads:
			return

		contains = False
		if mutex: self.adjustLock()
		try:
			for i in range(len(self.sourcesAdjusted)):
				sourceAdjusted = self.sourcesAdjusted[i]
				if sourceAdjusted['url'] == source['url']:
					# NB: Compare both debrid caches.
					# If there are different providers and/or different variations of the provider (for different foreing languages or umlauts), the same item might be detected by multiple providers.
					# This is especially important for debrid cached links. One provider might have it flagged as cache, the other one not. Then on the second run of the scraping procees, the values are read from database, and which ever one was written first to the DB will be returned.
					# Later pick the longest dict, since that one is expected to contains most metadata/info.

					# If any one is cached, make both cached.
					debridcache = sourceAdjusted[i]['debridcache'] if 'debridcache' in sourceAdjusted else None
					debridcacheNew = source['debridcache'] if 'debridcache' in source else None
					if debridcache == None: debridcache = debridcacheNew
					elif not debridcacheNew == None: debridcache = debridcache or debridcacheNew
					if not debridcache == None:
						sourceAdjusted['debridcache'] = debridcache
						source['debridcache'] = debridcache

					# Take the one with most info.
					length = len(tools.Converter.jsonTo(sourceAdjusted))
					lengthNew = len(tools.Converter.jsonTo(source))
					if length > lengthNew:
						self.sourcesAdjusted[i] = sourceAdjusted
					else:
						self.sourcesAdjusted[i] = source

					contains = True
					break
		except:
			pass
		finally:
			if mutex:
				try: self.adjustUnlock()
				except: pass
		return contains

	def adjustSourceUpdate(self, index, metadata = None, precheck = None, urlresolved = None, debridcache = None, hash = None, mutex = True):
		if self.stopThreads:
			return
		try:
			if index >= 0:
				if mutex: self.adjustLock()
				if not metadata == None:
					self.sourcesAdjusted[index]['metadata'] = metadata
				if not precheck == None:
					self.sourcesAdjusted[index]['precheck'] = precheck
				if not urlresolved == None:
					self.sourcesAdjusted[index]['urlresolved'] = urlresolved
				if not debridcache == None:
					self.sourcesAdjusted[index]['debridcache'] = debridcache
				if not hash == None:
					self.sourcesAdjusted[index]['hash'] = hash

				if mutex: self.adjustUnlock()
		except:
			pass
		finally:
			if mutex:
				try: self.adjustUnlock()
				except: pass

	# Write changes to database.
	def adjustSourceDatabase(self, timeout = 30):
		try:
			self.adjustLock()

			sources = {}
			for i in range(len(self.sourcesAdjusted)):
				try:
					# Make sure the metadata is updated with any new info in the source dictionary, such as debrid cache inspection.
					# Is only an observable problem with slow machines.
					metadata = metadatax.Metadata.initialize(self.sourcesAdjusted[i])
					metadata.update(self.sourcesAdjusted[i])
					self.sourcesAdjusted[i]['metadata'] = metadata

					result = copy.deepcopy(self.sourcesAdjusted[i])
					source = result['database']['source']
					mode = result['database']['mode']
					try: id = source + '_' + mode
					except: id = source
					result['metadata'] = metadatax.Metadata.uninitialize(result)

					if not id in sources:
						sources[id] = {
							'source' : source,
							'mode' : mode,
							'imdb' : result['database']['imdb'],
							'season' : result['database']['season'],
							'episode' : result['database']['episode'],
							'sources' : []
						}

					del result['database']
					sources[id]['sources'].append(result)
				except:
					pass

			# NB: Very often the execution on the databases throws an exception if multiple threads access the database at the same time.
			# NB: An OperationalError "database is locked" is thrown. Set a timeout to give the connection a few seconds to retry.
			# NB: This should not happen in this function, since it is only executed by 1 thread, but still give it a timeout, in case some scraping threads have not finished and also try to access it.
			dbcon = database.connect(self.sourceFile, timeout = timeout)
			dbcur = dbcon.cursor()
			timestamp = tools.Time.timestamp()

			for value in sources.itervalues():
				try:
					source = value['source']
					mode = value['mode']
					imdb = value['imdb']
					season = value['season']
					episode = value['episode']
					data = json.dumps(value['sources'])
					dbcur.execute("DELETE FROM sources WHERE source = '%s' AND mode = '%s' AND imdb = '%s' AND season = '%s' AND episode = '%s'" % (source, mode, imdb, season, episode))
					dbcur.execute("INSERT INTO sources Values (?, ?, ?, ?, ?, ?, ?)", (source, mode, imdb, season, episode, data, timestamp))
				except:
					pass
			dbcon.commit()
		except:
			tools.Logger.error()
		finally:
			try: self.adjustUnlock()
			except: pass

	def adjustSourceDone(self, index):
		try:
			self.adjustLock()
			if index >= 0 and index < len(self.statusAdjusted):
				self.statusAdjusted[index] = 'done'
			self.adjustUnlock()
		except:
			pass
		finally:
			try: self.adjustUnlock()
			except: pass

	def adjustSource(self, source, index):
		if self.stopThreads:
			self.adjustSourceDone(index)
			return None
		try:
			link = source['url']
			special = source['source'] == 'torrent' or source['source'] == 'usenet'
			status = network.Networker.StatusUnknown
			neter = None

			# Resolve Link
			if not special and (self.enabledPrecheck or self.enabledMetadata):
				if not 'urlresolved' in source or ('urlresolved' in source and not source['urlresolved']):
					link = network.Networker().resolve(source, clean = True)
					if link:
						source['urlresolved'] = link
					else:
						link = source['url']
				self.adjustSourceUpdate(index, urlresolved = link)

				neter = network.Networker(link)
				local = 'local' in source and source['local']

			# Debrid Cache
			# Do before precheck and metadata, because it is a lot faster and more important. So execute first.
			if special and self.enabledCache:
				# Do not automatically get the hash, since this will have to download the torrent/NZB files.
				# Sometimes more than 150 MB of torrents/NZBs can be downloaded on one go, wasting bandwidth and slowing down the addon/Kodi.
				download = False
				if source['source'] == 'torrent': download = tools.Settings.getBoolean('scraping.cache.preload.torrent')
				elif source['source'] == 'usenet': download = tools.Settings.getBoolean('scraping.cache.preload.usenet')

				container = network.Container(link = link, download = download)
				hash = container.hash()
				if not hash == None:
					self.adjustSourceUpdate(index, hash = hash)

			# Precheck
			if not special and self.enabledPrecheck:
				if local:
					status = network.Networker.StatusOnline
				elif not neter == None:
					neter.headers(timeout = tools.Settings.getInteger('scraping.precheck.timeout'))
					status = neter.check(content = True)
				self.adjustSourceUpdate(index, precheck = status)

			# Metadata
			if not special and self.enabledMetadata and status == network.Networker.StatusOnline:
				if index < 0: # Already in list.
					return None
				metadata = metadatax.Metadata(link = link)
				if not local:
					metadata.loadHeaders(neter, timeout = tools.Settings.getInteger('scraping.metadata.timeout'))
				self.adjustSourceUpdate(index, metadata = metadata)

		except:
			pass

		self.adjustSourceDone(index)
		if not self.threadsLimit == None: self.adjustSourceStart()
		return source


	def presetSources(self, url):
		try:
			interface.Loader.show()
			items = []

			for i in range(1, 5):
				name = tools.Settings.getString('providers.customization.presets.preset%d' % i)
				if not name == None and not name == '': items.append(name)

			itemCount = len(items)
			if itemCount == 0:
				interface.Loader.hide()
				interface.Dialog.notification(title = 35058, message = 35059, icon = interface.Dialog.IconError)
			else:
				automatic = tools.Settings.getBoolean('playback.automatic.enabled')
				labelManual = interface.Format.bold(interface.Translation.string(33110) + ': ')
				labelAutomatic = interface.Format.bold(interface.Translation.string(33800) + ': ')
				itemsManual = []
				itemsAutomatic = []
				for item in items:
					itemsManual.append(labelManual + item)
					itemsAutomatic.append(labelAutomatic + item)
				items = itemsManual + itemsAutomatic

				preset = interface.Dialog.options(title = 35058, items = items)
				if preset >= 0:
					if preset >= itemCount:
						preset -= itemCount
						select = 2
					else:
						select = tools.Settings.getInteger('interface.stream.list')
					preset += 1 # Settings start at 1.
					control.execute('RunPlugin(%s&select=%d&preset=%d)' % (url, select, preset))
		except:
			pass
		interface.Loader.hide()


	# [/BUBBLESCODE]


	def alterSources(self, url):
		try:
			interface.Loader.show()
			if tools.Settings.getBoolean('playback.automatic.enabled'):
				select = tools.Settings.getInteger('interface.stream.list')
			else:
				select = 2
			control.execute('RunPlugin(%s&select=%d)' % (url, select))
		except:
			interface.Loader.hide()


	def clearSources(self, confirm = False):
		try:
			if confirm:
				control.idle()
				yes = interface.Dialog.option(33042)
				if not yes: return

			control.makeFile(control.dataPath)
			dbcon = database.connect(control.providercacheFile)
			dbcur = dbcon.cursor()
			dbcur.execute("DROP TABLE IF EXISTS sources")
			dbcur.execute("DROP TABLE IF EXISTS links")

			# These are the legacy tables. Can be removed in a lter version.
			# Also in clearSourcesOld()
			dbcur.execute("DROP TABLE IF EXISTS rel_url")
			dbcur.execute("DROP TABLE IF EXISTS rel_src")

			dbcur.execute("VACUUM")
			dbcon.commit()

			if confirm:
				interface.Dialog.notification(33043, sound = True, icon = interface.Dialog.IconInformation)
		except:
			pass

	def clearSourcesOld(self, wait = True):
		def _clearSourcesOld():
			try:
				timestamp = tools.Time.timestamp() - 7200 # Must be the same delay as for retrieving the sources, that is 120 minutes.
				control.makeFile(control.dataPath)
				dbcon = database.connect(control.providercacheFile)
				dbcur = dbcon.cursor()

				# These are the legacy tables. Can be removed in a lter version.
				# Also in clearSources()
				dbcur.execute("DROP TABLE IF EXISTS rel_url")
				dbcur.execute("DROP TABLE IF EXISTS rel_src")

				dbcur.execute("DELETE FROM sources WHERE time < %d" % timestamp)
				dbcon.commit()
			except:
				pass
		thread = workers.Thread(_clearSourcesOld)
		thread.start()
		if wait: thread.join()

	def sourcesFilter(self, autoplay, title, meta):
		try:
			def filterFlag(source, value):
				return value in source and source[value] == True

			def filterSetting(setting):
				if autoplay: return control.setting('playback.automatic.' + setting)
				else: return control.setting('playback.manual.' + setting)

			def filterMetadata(sources, filters):
				try:
					result = []
					for filter in filters:
						subresult = []
						i = 0
						length = len(sources)
						while i < length:
							source = sources[i]
							if source['quality'] == filter:
								subresult.append(source)
								del sources[i]
								i -= 1
							i += 1
							length = len(sources)
						result += filterMetadataQuality(subresult)
					return result
				except:
					return sources

			def filterMetadataQuality(sources):
				result = []
				resultH265 = [[], [], [], [], [], [], [], [], [], [], [], []]
				resultH264 = [[], [], [], [], [], [], [], [], [], [], [], []]
				resultOther = [[], [], [], [], [], [], [], [], [], [], []]
				resultRest = []

				source = None
				for i in range(len(sources)):
					source = sources[i]
					metadata = source['metadata']
					videoCodec = metadata.videoCodec()
					audioChannels = metadata.audioChannels()
					audioCodec = metadata.audioCodec()

					if 'H265' == videoCodec:
						if '8CH' == audioChannels:
							if 'DTS' == audioCodec: resultH265[0].append(source)
							elif 'DD' == audioCodec: resultH265[1].append(source)
							else: resultH265[2].append(source)
						elif '6CH' == audioChannels:
							if 'DTS' == audioCodec: resultH265[3].append(source)
							elif 'DD' == audioCodec: resultH265[4].append(source)
							else: resultH265[5].append(source)
						elif 'DTS' == audioCodec:
							resultH265[6].append(source)
						elif 'DD' == audioCodec:
							resultH265[7].append(source)
						elif '2CH' == audioChannels:
							if 'DTS' == audioCodec: resultH265[8].append(source)
							elif 'DD' == audioCodec: resultH265[9].append(source)
							else: resultH265[10].append(source)
						else:
							resultH265[11].append(source)
					elif 'H264' == videoCodec:
						if '8CH' == audioChannels:
							if 'DTS' == audioCodec: resultH264[0].append(source)
							elif 'DD' == audioCodec: resultH264[1].append(source)
							else: resultH264[2].append(source)
						elif '6CH' == audioChannels:
							if 'DTS' == audioCodec: resultH264[3].append(source)
							elif 'DD' == audioCodec: resultH264[4].append(source)
							else: resultH264[5].append(source)
						elif 'DTS' == audioCodec:
							resultH264[6].append(source)
						elif 'DD' == audioCodec:
							resultH264[7].append(source)
						elif '2CH' == audioChannels:
							if 'DTS' == audioCodec: resultH264[8].append(source)
							elif 'DD' == audioCodec: resultH264[9].append(source)
							else: resultH264[10].append(source)
						else:
							resultH264[11].append(source)
					else:
						if '8CH' == audioChannels:
							if 'DTS' == audioCodec: resultOther[0].append(source)
							elif 'DD' == audioCodec: resultOther[1].append(source)
							else: resultOther[2].append(source)
						elif '6CH' == audioChannels:
							if 'DTS' == audioCodec: resultOther[3].append(source)
							elif 'DD' == audioCodec: resultOther[4].append(source)
							else: resultOther[5].append(source)
						elif 'DTS' == audioCodec:
							resultOther[6].append(source)
						elif 'DD' == audioCodec:
							resultOther[7].append(source)
						elif '2CH' == audioChannels:
							if 'DTS' == audioCodec: resultOther[8].append(source)
							elif 'DD' == audioCodec: resultOther[9].append(source)
							else: resultOther[10].append(source)
						else:
							resultRest.append(source)

				for i in range(len(resultH265)):
					result += resultH265[i]
				for i in range(len(resultH264)):
					result += resultH264[i]
				for i in range(len(resultOther)):
					result += resultOther[i]
				result += resultRest

				result = filterMetadataSpecial(result)
				return result

			def filterMetadataSpecial(results):
				filter1 = []
				filter2 = []
				filter3 = []
				filter4 = []
				filter5 = []
				for s in results:
					if s['metadata'].premium(): filter1.append(s)
					elif s['metadata'].cached(): filter2.append(s)
					elif s['metadata'].direct(): filter3.append(s)
					elif s['metadata'].debrid(): filter4.append(s)
					else: filter5.append(s)
				filter1 = filterMetadataPrecheck(filter1)
				filter2 = filterMetadataPrecheck(filter2)
				filter3 = filterMetadataPrecheck(filter3)
				filter4 = filterMetadataPrecheck(filter4)
				filter5 = filterMetadataPrecheck(filter5)
				return filter1 + filter2 + filter3 + filter4 + filter5

			def filterMetadataPrecheck(results):
				filter1 = []
				filter2 = []
				filter3 = []
				for s in results:
					check = s['metadata'].precheck()
					if check == network.Networker.StatusOnline: filter1.append(s)
					elif check == network.Networker.StatusUnknown: filter2.append(s)
					else: filter3.append(s)
				return filter1 + filter2 + filter3

			def filterDuplicates(sources):
				def filterLink(link):
					container = network.Container(link)
					if container.torrentIsMagnet():
						return container.torrentMagnetClean() # Clean magnet from trackers, name, domain, etc.
					else:
						return network.Networker(link).link() # Clean link from HTTP headers.

				result = []
				linksNormal = []
				linksResolved = []
				linksHashes = []
				linksSources = []

				for source in sources:
					# NB: Only remove duplicates if their source is the same. This ensures that links from direct sources are not removed (Eg: Premiumize Direct vs Premiumize Torrent).

					linkNormal = filterLink(source['url'])
					try:
						index = linksNormal.index(linkNormal)
						if index >= 0 and source['source'] == linksSources[index]:
							continue
					except: pass

					try:
						linkResolved = filterLink(source['urlresolved']) if 'urlresolved' in source else None
						if not linkResolved == None:
							index = linksResolved.index(linkResolved)
							if index >= 0 and source['source'] == linksSources[index]:
								continue
					except: pass

					try:
						if 'hash' in source and not source['hash'] == None:
							index = linksHashes.index(source['hash'])
							if index >= 0 and source['source'] == linksSources[index]:
								continue
					except: pass

					result.append(source)
					linksNormal.append(linkNormal)
					linksResolved.append(linkResolved)
					linksHashes.append(source['hash'] if 'hash' in source else None)
					linksSources.append(source['source'])

				return result

			####################################################################################
			# PREPROCESSING
			####################################################################################

			# Filter out duplicates (for original movie title)
			# Do this at the end again.
			self.sources = filterDuplicates(self.sources)

			# Convert Quality
			for i in range(len(self.sources)):
				self.sources[i]['quality'] = metadatax.Metadata.videoQualityConvert(self.sources[i]['quality'])

			# Create Metadata
			if isinstance(meta, basestring):
				meta = json.loads(meta)
			for i in range(len(self.sources)):
				self.sources[i]['metadata'] = metadatax.Metadata.initialize(title = title, source = self.sources[i])

			####################################################################################
			# METADATA ELIMINATE
			####################################################################################

			# Filter - Unsupported
			# Create 3 handlers in order to reduce overhead in the handlers initialization.
			handleDirect = handler.Handler(type = handler.Handler.TypeDirect)
			handleTorrent = handler.Handler(type = handler.Handler.TypeTorrent)
			handleUsenet = handler.Handler(type = handler.Handler.TypeUsenet)
			handleHoster = handler.Handler(type = handler.Handler.TypeHoster)
			filter = []
			for i in self.sources:
				source = i['source']
				if source == handler.Handler.TypeTorrent:
					if handleTorrent.supported(i): filter.append(i)
				elif source == handler.Handler.TypeUsenet:
					if handleTorrent.supported(i): filter.append(i)
				elif 'direct' in i and i['direct']:
					if handleDirect.supported(i): filter.append(i)
				else:
					if handleHoster.supported(i): filter.append(i)
			self.sources = filter

			# Filter - Prechecks
			precheck = filterSetting('provider.precheck') == 'true' and tools.System.developers()
			if precheck:
				self.sources = [i for i in self.sources if not 'precheck' in i or not i['precheck'] == network.Networker.StatusOffline]

			# Filter - Editions
			editions = int(filterSetting('additional.editions'))
			if editions == 1:
				self.sources = [i for i in self.sources if not i['metadata'].edition()]
			elif editions == 2:
				self.sources = [i for i in self.sources if i['metadata'].edition()]

			# Filter - Releases
			releases = tools.Settings.customGetReleases('automatic' if autoplay else 'manual')
			if releases and not len(releases) == len(metadatax.Metadata.DictionaryReleases):
				filter = []
				for i in self.sources:
					release = i['metadata'].release(full = False)
					if release and release in releases:
						filter.append(i)
				self.sources = filter

			# Filter - Uploaders
			uploaders = tools.Settings.customGetUploaders('automatic' if autoplay else 'manual')
			if uploaders and not len(uploaders) == len(metadatax.Metadata.DictionaryUploaders):
				filter = []
				for i in self.sources:
					uploader = i['metadata'].uploader()
					if uploader and any(u in uploaders for u in uploader):
						filter.append(i)
				self.sources = filter

			# Filter - Video Codec
			videoCodec = int(filterSetting('video.codec'))
			if videoCodec == 1:
				self.sources = [i for i in self.sources if i['metadata'].videoCodec() == 'H265' or i['metadata'].videoCodec() == 'H264']
			elif videoCodec == 2:
				self.sources = [i for i in self.sources if i['metadata'].videoCodec() == 'H265']
			elif videoCodec == 3:
				self.sources = [i for i in self.sources if i['metadata'].videoCodec() == 'H264']

			# Filter - Video 3D
			video3D = int(filterSetting('video.3d'))
			if video3D == 1:
				self.sources = [i for i in self.sources if not i['metadata'].videoExtra() == '3D']
			elif video3D == 2:
				self.sources = [i for i in self.sources if i['metadata'].videoExtra() == '3D']

			# Filter - Audio Channels
			audioChannels = int(filterSetting('audio.channels'))
			if audioChannels == 1:
				self.sources = [i for i in self.sources if i['metadata'].audioChannels() == '8CH' or i['metadata'].audioChannels() == '6CH']
			elif audioChannels == 2:
				self.sources = [i for i in self.sources if i['metadata'].audioChannels() == '8CH']
			elif audioChannels == 3:
				self.sources = [i for i in self.sources if i['metadata'].audioChannels() == '6CH']
			elif audioChannels == 4:
				self.sources = [i for i in self.sources if i['metadata'].audioChannels() == '2CH']

			# Filter - Audio Codec
			audioCodec = int(filterSetting('audio.codec'))
			if audioCodec == 1:
				self.sources = [i for i in self.sources if i['metadata'].audioCodec() == 'DTS' or i['metadata'].audioCodec() == 'DD' or i['metadata'].audioCodec() == 'AAC']
			elif audioCodec == 2:
				self.sources = [i for i in self.sources if i['metadata'].audioCodec() == 'DTS' or i['metadata'].audioCodec() == 'DD']
			elif audioCodec == 3:
				self.sources = [i for i in self.sources if i['metadata'].audioCodec() == 'DTS']
			elif audioCodec == 4:
				self.sources = [i for i in self.sources if i['metadata'].audioCodec() == 'DD']
			elif audioCodec == 5:
				self.sources = [i for i in self.sources if i['metadata'].audioCodec() == 'AAC']

			# Filter - Audio Language
			audioLanguage = int(filterSetting('audio.language'))
			if audioLanguage == 1:
				audioLanguageUnknown = tools.Converter.boolean(filterSetting('audio.language.unknown'))
				if not audioLanguageUnknown:
					self.sources = [i for i in self.sources if not i['metadata'].audioLanguages() == None and len(i['metadata'].audioLanguages()) > 0]

				audioLanguages = []
				if tools.Language.customization():
					language = filterSetting('audio.language.primary')
					if not language == 'None': audioLanguages.append(tools.Language.code(language))
					language = filterSetting('audio.language.secondary')
					if not language == 'None': audioLanguages.append(tools.Language.code(language))
					language = filterSetting('audio.language.tertiary')
					if not language == 'None': audioLanguages.append(tools.Language.code(language))
				else:
					audioLanguages = [language[0] for language in tools.Language.settings()]
				audioLanguages = list(set(audioLanguages))
				filter = []
				for i in self.sources:
					languages = i['metadata'].audioLanguages()
					if audioLanguageUnknown and (languages == None or len(languages) == 0):
						filter.append(i)
					else:
						if languages == None or len(languages) == 0:
							languages = []
						else:
							languages = [l[0] for l in languages]
						if any(l in audioLanguages for l in languages):
							filter.append(i)
				self.sources = filter

			# Filter - Dubbed Audio
			audioDubbed = int(filterSetting('audio.dubbed'))
			if audioDubbed == 1:
				self.sources = [i for i in self.sources if not i['metadata'].audioDubbed()]
			elif audioDubbed == 2:
				self.sources = [i for i in self.sources if i['metadata'].audioDubbed()]

			# Filter - Subtitles Softcoded
			subtitlesSoftcoded = int(filterSetting('subtitles.softcoded'))
			if subtitlesSoftcoded == 1:
				self.sources = [i for i in self.sources if not i['metadata'].subtitlesIsSoft()]
			elif subtitlesSoftcoded == 2:
				self.sources = [i for i in self.sources if i['metadata'].subtitlesIsSoft()]

			# Filter - Subtitles Hardcoded
			subtitlesHardcoded = int(filterSetting('subtitles.hardcoded'))
			if subtitlesHardcoded == 1:
				self.sources = [i for i in self.sources if not i['metadata'].subtitlesIsHard()]
			elif subtitlesHardcoded == 2:
				self.sources = [i for i in self.sources if i['metadata'].subtitlesIsHard()]

			# Filter - Bandwidth
			bandwidthMaximum = int(filterSetting('data.bandwidth.maximum'))
			bandwidthUnknown = filterSetting('data.bandwidth.unknown') == 'true'
			duration = int(meta['duration']) if meta and 'duration' in meta else None

			if bandwidthMaximum > 0:
				settingsBandwidth = tools.Settings.data()
				indexStart = settingsBandwidth.find('playback.automatic.data.bandwidth.maximum' if autoplay else 'playback.manual.data.bandwidth.maximum')
				indexStart = settingsBandwidth.find('lvalues', indexStart) + 9
				indexEnd = settingsBandwidth.find('"', indexStart)
				settingsBandwidth = settingsBandwidth[indexStart : indexEnd]
				settingsBandwidth = settingsBandwidth.split('|')
				settingsBandwidth = interface.Translation.string(int(settingsBandwidth[bandwidthMaximum]))

				# All values are calculated at 90% the line speed, due to lag, disconnects, buffering, etc.
				bandwidthMaximum = int(convert.ConverterSpeed(value = settingsBandwidth).value(unit = convert.ConverterSpeed.Byte) * 0.90)

				if bandwidthUnknown:
					self.sources = [i for i in self.sources if not duration or not i['metadata'].size() or i['metadata'].size() / duration <= bandwidthMaximum]
				else:
					self.sources = [i for i in self.sources if duration and i['metadata'].size() and i['metadata'].size() / duration <= bandwidthMaximum]

			# Filter - Providers
			providerSelection = int(filterSetting('provider.selection'))
			providerSelectionHoster = providerSelection == 0 or providerSelection == 1 or providerSelection == 2 or providerSelection == 4
			providerSelectionTorrents = providerSelection == 0 or providerSelection == 1 or providerSelection == 3 or providerSelection == 5
			providerSelectionUsenet = providerSelection == 0 or providerSelection == 2 or providerSelection == 3 or providerSelection == 6

			# Filter - Hosters
			if not providerSelectionHoster:
				self.sources = [i for i in self.sources if not i['metadata'].isHoster()]

			# Filter - Torrents
			if providerSelectionTorrents:

				# Filter - Torrent Cache
				torrentCache = int(filterSetting('provider.torrent.cache'))
				torrentCacheInclude = torrentCache == 0
				torrentCacheExclude = torrentCache == 1
				torrentCacheRequire = torrentCache == 2
				if torrentCacheExclude:
					self.sources = [i for i in self.sources if not i['metadata'].isTorrent() or not 'debridcache' in i or i['debridcache'] == False]
				elif torrentCacheRequire:
					self.sources = [i for i in self.sources if not i['metadata'].isTorrent() or ('debridcache' in i and i['debridcache'] == True)]

				# Filter - Torrent Seeds
				if not torrentCacheRequire:
					seeds = int(filterSetting('provider.torrent.seeds'))
					if seeds == 1: seeds = 10
					elif seeds == 2: seeds = 20
					elif seeds == 3: seeds = 50
					elif seeds == 4: seeds = 100
					elif seeds == 5: seeds = 200
					elif seeds == 6: seeds = 500
					elif seeds == 7: seeds = 1000
					elif seeds == 8: seeds = 2000
					elif seeds == 9: seeds = 5000
					self.sources = [i for i in self.sources if not i['metadata'].isTorrent() or i['metadata'].seeds() >= seeds]
			else:
				self.sources = [i for i in self.sources if not i['metadata'].isTorrent()]

			# Filter - Usenet
			if providerSelectionUsenet:
				# Filter - Usenet Cache
				usenetCache = int(filterSetting('provider.usenet.cache'))
				usenetCacheInclude = usenetCache == 0
				usenetCacheExclude = usenetCache == 1
				usenetCacheRequire = usenetCache == 2
				if usenetCacheExclude:
					self.sources = [i for i in self.sources if not i['metadata'].isUsenet() or not 'debridcache' in i or i['debridcache'] == False]
				elif usenetCacheRequire:
					self.sources = [i for i in self.sources if not i['metadata'].isUsenet() or ('debridcache' in i and i['debridcache'] == True)]

				# Filter - Usenet Age
				age = int(filterSetting('provider.usenet.age'))
				if age > 0 and not usenetCacheRequire:
					if age == 1: age = 1825
					elif age == 2: age = 1460
					elif age == 3: age = 1095
					elif age == 4: age = 730
					elif age == 5: age = 365
					elif age == 6: age = 183
					elif age == 7: age = 91
					elif age == 8: age = 61
					elif age == 9: age = 31
					elif age == 10: age = 14
					elif age == 11: age = 7
					elif age == 12: age = 3
					elif age == 13: age = 2
					elif age == 14: age = 1
					self.sources = [i for i in self.sources if not i['metadata'].isUsenet() or i['metadata'].age() <= age]
			else:
				self.sources = [i for i in self.sources if not i['metadata'].isUsenet()]

			# Filter - Debrid Cost
			costMaximum = int(filterSetting('service.cost'))
			premiumize = debridx.Premiumize()
			if costMaximum > 0 and premiumize.accountValid():
				filter = []
				for i in self.sources:
					if ('debrid' in i and i['debrid'].lower() == 'premiumize') or i['source'].lower() == 'premiumize':
						try: cost = premiumize.service(i['source'].lower().rsplit('.', 1)[0])['usage']['cost']['value']
						except: cost = None
						if cost == None or cost <= costMaximum:
							filter.append(i)
					else:
						filter.append(i)
				self.sources = filter

			# Filter - Captcha
			if filterSetting('provider.captcha') == 'true':
				filter = [i for i in self.sources if i['source'].lower() in self.hostcapDict and not 'debrid' in i]
				self.sources = [i for i in self.sources if not i in filter]

			# Filter - Block
			filter = [i for i in self.sources if i['source'].lower() in self.hostblockDict and not 'debrid' in i]
			self.sources = [i for i in self.sources if not i in filter]

			####################################################################################
			# METADATA SORT INTERNAL
			####################################################################################

			# Filter - Local
			filterLocal = [i for i in self.sources if 'local' in i and i['local'] == True]
			self.sources = [i for i in self.sources if not i in filterLocal]
			filterLocal = filterMetadata(filterLocal, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720', 'SD'])

			# Filter - Add Hosters that are supported by a Debrid service.
			if debrid.status():
				filter = []
				for i in range(len(self.sources)):
					if not 'debrid' in self.sources[i]:
						self.sources[i]['debrid'] = False
				filter += [i for i in self.sources if i['debrid'] == True]
				filter += [i for i in self.sources if i['debrid'] == False]
				self.sources = filter

			# Filter - Video Quality
			videoQualityMinimum = filterSetting('video.quality.minimum')
			videoQualityMinimum = 0 if not videoQualityMinimum or videoQualityMinimum == '' else int(videoQualityMinimum)
			videoQualityMaximum = filterSetting('video.quality.maximum')
			videoQualityMaximum = 0 if not videoQualityMaximum or videoQualityMaximum == '' else int(videoQualityMaximum)
			if videoQualityMinimum > videoQualityMaximum:
				videoQualityMinimum, videoQualityMaximum = videoQualityMinimum, videoQualityMaximum # Swap

			metadata = metadatax.Metadata()
			qualities = [None] + metadata.VideoQualityOrder
			videoQualityFrom = qualities[videoQualityMinimum]
			videoQualityTo = qualities[videoQualityMaximum]
			# Only get the indexes once, otherwise has to search for it for every stream.
			videoQualityFrom = metadata.videoQualityIndex(videoQualityFrom)
			videoQualityTo = metadata.videoQualityIndex(videoQualityTo)
			self.sources = [i for i in self.sources if metadata.videoQualityRange(i['quality'], videoQualityFrom, videoQualityTo)]

			# Filter - Services
			serviceSelection = int(filterSetting('service.selection'))
			serviceSelectionDebrid = serviceSelection == 0 or serviceSelection == 1 or serviceSelection == 2 or serviceSelection == 4
			serviceSelectionMembers = serviceSelection == 0 or serviceSelection == 1 or serviceSelection == 3 or serviceSelection == 5
			serviceSelectionFree = serviceSelection == 0 or serviceSelection == 2 or serviceSelection == 3 or serviceSelection == 6

			# Filter - HD - Premium
			filterPremium = [i for i in self.sources if filterFlag(i, 'premium') and not i['quality'] == 'SD' and not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterPremium]
			if serviceSelectionDebrid:
				filterPremium = filterMetadata(filterPremium, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])
			else:
				filterPremium = []

			# Filter - HD - Debrid
			filterDebrid = [i for i in self.sources if filterFlag(i, 'debrid') and not i['quality'] == 'SD' and not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterDebrid]
			if serviceSelectionDebrid:
				filterDebrid = filterMetadata(filterDebrid, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])
			else:
				filterDebrid = []

			# Filter - HD - Direct
			filterDirect = [i for i in self.sources if filterFlag(i, 'direct') and not i['quality'] == 'SD' and not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterDirect]
			if serviceSelectionFree:
				filterDirect = filterMetadata(filterDirect, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])
			else:
				filterDirect = []

			# Filter - HD - Member
			filterMember = [i for i in self.sources if filterFlag(i, 'memberonly') and not i['quality'] == 'SD' and not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterMember]
			if serviceSelectionMembers:
				filterMember = filterMetadata(filterMember, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])
			else:
				filterMember = []

			# Filter - HD - Free
			filterFree = [i for i in self.sources if not i['quality'] == 'SD' and not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterFree]
			if serviceSelectionFree:
				filterFree = filterMetadata(filterFree, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])
			else:
				filterFree = []

			# Filter - SD
			filterSd = [i for i in self.sources if not 'SCR' in i['quality'] and not 'CAM' in i['quality']]
			self.sources = [i for i in self.sources if not i in filterSd]
			filter = []
			if serviceSelectionDebrid:
				filter += filterMetadata([i for i in filterSd if filterFlag(i, 'premium')], ['SD'])
				filter += filterMetadata([i for i in filterSd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SD'])
			if serviceSelectionFree:
				filter += filterMetadata([i for i in filterSd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SD'])
			if serviceSelectionMembers:
				filter += filterMetadata([i for i in filterSd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['SD'])
			if serviceSelectionFree:
				filter += filterMetadata([i for i in filterSd if not filterFlag(i, 'premium')  and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['SD'])
			filterSd = filter

			# Filter - Combine
			filterLd = self.sources
			self.sources = []
			self.sources += filterLocal

			# Sort again to make sure HD streams from free hosters go to the top.
			filter = []
			filter += filterPremium
			filter += filterDebrid
			filter += filterDirect
			filter += filterMember
			filter += filterFree
			self.sources += filterMetadata(filter, ['HD8K', 'HD6K', 'HD4K', 'HD2K', 'HD1080', 'HD720'])

			self.sources += filterMetadataSpecial(filterSd)

			# Filter - LD
			if len(self.sources) < 50:
				filter = []

				# SCR1080
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['SCR1080'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR1080'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR1080'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['SCR1080'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['SCR1080'])

				# SCR720
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['SCR720'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR720'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR720'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['SCR720'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['SCR720'])

				# SCR
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['SCR'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['SCR'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['SCR'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['SCR'])

				# CAM1080
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['CAM1080'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM1080'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM1080'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['CAM1080'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['CAM1080'])

				# CAM720
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['CAM720'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM720'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM720'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['CAM720'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['CAM720'])

				# CAM
				if serviceSelectionDebrid:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'premium')], ['CAM'])
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'direct') and not filterFlag(i, 'debrid') and not filterFlag(i, 'premium')], ['CAM'])
				if serviceSelectionMembers:
					filter += filterMetadata([i for i in filterLd if filterFlag(i, 'memberonly') and not filterFlag(i, 'premium') and not filterFlag(i, 'debrid') and not filterFlag(i, 'direct')], ['CAM'])
				if serviceSelectionFree:
					filter += filterMetadata([i for i in filterLd if not not filterFlag(i, 'premium') and filterFlag(i, 'debrid') and not filterFlag(i, 'direct') and not filterFlag(i, 'memberonly')], ['CAM'])

				self.sources += filterMetadata(filter, ['SCR1080', 'SCR720', 'SCR', 'CAM1080', 'CAM720', 'CAM'])

			####################################################################################
			# METADATA SORT EXTERNAL
			####################################################################################

			# Reverse video quality order.
			if int(filterSetting('sort.quality')) == 1:
				filter = []
				order = metadatax.Metadata.VideoQualityOrder
				for o in order:
					for i in self.sources:
						if i['quality'] == o:
							filter.append(i)
				self.sources = filter

			# Sort according to provider
			if int(filterSetting('sort.order')) == 1:
				filter1 = []
				filter2 = []
				filter3 = self.sources

				# Always list local first.
				for j in filter3:
					try:
						if j['local']:
							filter1.append(j)
						else:
							filter2.append(j)
					except:
						filter2.append(j)
				filter3 = filter2
				filter2 = []

				# Rest of the items sorted according to provider.
				for i in range(1,11):
					setting = filterSetting('sort.provider%d' % i)
					if not setting == None and not setting == '':
						for j in filter3:
							if setting == j['provider']:
								filter1.append(j)
							else:
								filter2.append(j)
						filter3 = filter2
						filter2 = []

				self.sources = filter1 + filter3

			# Sort according to priority
			if tools.Converter.boolean(filterSetting('sort.priority.enabled')):
				filter = [[], [], [], [], []]
				optionLocal = int(filterSetting('sort.priority.local'))
				optionPremium = int(filterSetting('sort.priority.premium'))
				optionCached = int(filterSetting('sort.priority.cached'))
				optionDirect = int(filterSetting('sort.priority.direct'))

				for i in self.sources:
					if 'local' in i and i['local']:
						filter[optionLocal].append(i)
					elif 'premium' in i and i['premium']:
						filter[optionPremium].append(i)
					elif 'debridcache' in i and i['debridcache']:
						filter[optionCached].append(i)
					elif 'direct' in i and i['direct']:
						filter[optionDirect].append(i)
					else:
						filter[0].append(i)

				self.sources = filter[1] + filter[2] + filter[3] + filter[4] + filter[0]

			####################################################################################
			# POSTPROCESSING
			####################################################################################

			# Filter out duplicates (for original movie title)
			# This must be done at the end, because the filters someties add duplicates (eg: the filterDebrid, filterMember, and filterFree functions).
			# Can also happen if a link is member and debrid, will be filtered and added twice.
			self.sources = filterDuplicates(self.sources)

			# Filter - Limit
			self.sources = self.sources[:2000]

			####################################################################################
			# INTERFACE
			####################################################################################

			debridLabel = interface.Translation.string(33209)
			handlePremiumize = handler.HandlePremiumize()

			# Use the same object, because otherwise it will send a lot of account status request to the Premiumize server, each time a new Premiumize instance is created inside the for-loop.
			premiumize = debridx.Premiumize()
			premiumizeInformation = tools.Settings.getInteger('interface.information.premiumize')
			premiumizeInformationUsage = None
			if premiumizeInformation > 0 and premiumize.accountValid():
				if premiumizeInformation == 1 or premiumizeInformation == 3 or premiumizeInformation == 4 or premiumizeInformation == 7:
					try: premiumizeInformationUsage = premiumize.account()['usage']['consumed']['description']
					except: pass

			easynews = debridx.EasyNews()
			easynewsInformation = tools.Settings.getInteger('interface.information.easynews')
			easynewsInformationUsage = None
			if easynewsInformation > 0 and easynews.accountValid():
				try:
					easynewsInformationUsage = []
					usage = easynews.account()['usage']
					if easynewsInformation == 1: easynewsInformationUsage.append('%s Consumed' % (usage['consumed']['description']))
					elif easynewsInformation == 2: easynewsInformationUsage.append('%s Remaining' % (usage['remaining']['description']))
					elif easynewsInformation == 3: easynewsInformationUsage.append('%s Total' % (usage['total']['size']['description']))
					elif easynewsInformation == 4: easynewsInformationUsage.append('%s Consumed' % (usage['consumed']['size']['description']))
					elif easynewsInformation == 5: easynewsInformationUsage.append('%s Remaining' % (usage['remaining']['size']['description']))
					elif easynewsInformation == 6: easynewsInformationUsage.append('%s ()%s) Consumed' % (usage['consumed']['size']['description'], usage['consumed']['description']))
					elif easynewsInformation == 7: easynewsInformationUsage.append('%s (%s) Remaining' % (usage['remaining']['size']['description'], usage['remaining']['description']))
					if len(easynewsInformationUsage) == 0: easynewsInformationUsage = None
					else: easynewsInformationUsage = interface.Format.fontSeparator().join(easynewsInformationUsage)
				except:
					easynewsInformationUsage = None

			precheck = tools.System.developers() and tools.Settings.getBoolean('scraping.precheck.enabled')
			layout = tools.Settings.getInteger('interface.information.layout')
			layoutColor = tools.Settings.getBoolean('interface.information.layout.color')
			layoutPadding = tools.Settings.getInteger('interface.information.layout.padding') # Try with Confluence. 3 and 3.5 is not enough. 4 by default.
			layoutShort = layout == 0
			layoutLong = layout == 1
			layoutMultiple = layout == 2

			showType = tools.Settings.getBoolean('interface.information.type')
			showProvider = tools.Settings.getBoolean('interface.information.provider')
			showRelease = tools.Settings.getBoolean('interface.information.release')
			showUploader = tools.Settings.getBoolean('interface.information.uploader')

			for i in range(len(self.sources)):
				source = self.sources[i]['source'].lower().rsplit('.', 1)[0]
				pro = re.sub('v\d*$', '', self.sources[i]['provider'])
				metadata = self.sources[i]['metadata']
				number = '%02d' % int(i + 1)

				debridHas = 'debrid' in self.sources[i] and self.sources[i]['debrid']
				if source == 'torrent' or source == 'usenet':
					valueFirst = source if showType else None
					valueSecond = pro if showProvider else None
				elif 'local' in self.sources[i] and self.sources[i]['local']:
					valueFirst = source if showType else None
					valueSecond = pro if showProvider else None
				else:
					valueFirst = pro if showType else None
					valueSecond = source if showProvider else None

				if 'exact' in self.sources[i] and self.sources[i]['exact'] and 'file' in self.sources[i] and self.sources[i]['file']:
					valueSecond = self.sources[i]['file']

				infos = []
				infos.append(interface.Format.font(number, bold = True))
				if layoutShort or layoutLong:
					infos.append(metadata.information(format = True, precheck = precheck, information = metadatax.Metadata.InformationEssential, release = showRelease, uploader = showUploader))
				if valueFirst and not valueFirst == '' and not valueFirst == '0':
					infos.append(interface.Format.font(valueFirst, bold = True, uppercase = True))
				if valueSecond and not valueSecond == '' and not valueSecond == '0':
					if not valueFirst or not valueSecond or not valueFirst.lower() == valueSecond.lower():
						infos.append(interface.Format.font(valueSecond, uppercase = True)) # Local library has not source.
				labelTop = interface.Format.fontSeparator().join(infos)

				if premiumizeInformation > 0 and ((debridHas and handlePremiumize.supported(self.sources[i]) or source == 'premiumize')):
					try: # Somtimes Premiumize().service(source) failes. In such a case, just ignore it.
						cost = None
						limit = None
						service = premiumize.service(source)
						if premiumizeInformation == 1 or premiumizeInformation == 2 or premiumizeInformation == 3 or premiumizeInformation == 5:
							cost = service['usage']['cost']['description']
						if premiumizeInformation == 1 or premiumizeInformation == 2 or premiumizeInformation == 4 or premiumizeInformation == 6:
							limit = service['usage']['limit']['description']
						information = []
						if cost: information.append(cost)
						if premiumizeInformationUsage: information.append(premiumizeInformationUsage)
						if limit: information.append(limit)
						if len(information) > 0: labelTop += interface.Format.fontSeparator() + interface.Format.fontSeparator().join(information)
					except:
						tools.Logger.error()
						pass
				elif pro.lower() == 'easynews' and easynewsInformationUsage:
					labelTop += interface.Format.fontSeparator() + easynewsInformationUsage

				labelTop = re.sub(' +',' ', labelTop)
				label = ''

				if layoutShort:
					label = labelTop
				elif layoutLong:
					labelBottom = metadata.information(format = True, sizeLimit = True, precheck = precheck, information = metadatax.Metadata.InformationNonessential, release = showRelease, uploader = showUploader, color = layoutColor)
					labelBottom = re.sub(' +',' ', labelBottom)
					label = labelTop + interface.Format.fontSeparator() + labelBottom
				elif layoutMultiple:
					labelBottom = metadata.information(format = True, sizeLimit = True, precheck = precheck, release = showRelease, uploader = showUploader, color = layoutColor)
					labelBottom = re.sub(' +',' ', labelBottom)
					if layoutPadding <= 0:
						spaceTop = ''
						spaceBottom = ''
					else:
						# Spaces needed, otherwise the second line is cut off when shorter than the first line
						spaceTop = 0
						spaceBottom = 0
						lengthTop = len(re.sub('\\[(.*?)\\]', '', labelTop))
						lengthBottom = len(re.sub('\\[(.*?)\\]', '', labelBottom))
						if lengthBottom > lengthTop:
							spaceTop = int((lengthBottom - lengthTop) * layoutPadding)
						else:
							spaceBottom = int((lengthBottom - lengthTop) * layoutPadding)
						spaceTop = ' ' * max(8, spaceTop)
						spaceBottom = ' ' * max(8, spaceBottom)
					label = labelTop + spaceTop + interface.Format.fontNewline() + labelBottom + spaceBottom

				self.sources[i]['label'] = label
		except:
			tools.Logger.error()

		interface.Loader.hide() # Sometimes on Kodi 16 the loader is still showing.
		return self.sources

	def sourcesResolve(self, item, info = False, internal = False, download = False, handle = None, handleMode = None, handleClose = True, resolve = network.Networker.ResolveService):
		try:
			if not internal: self.url = None
			u = url = item['url']

			if resolve == network.Networker.ResolveNone:
				self.url = url
				return url

			# BUBBLES: try important here, since debird not yet set for early precheck resolving.
			try: d = item['debrid']
			except: d =''

			popups = (not internal)

			source = provider.Provider.provider(item['provider'].lower(), enabled = False, local = True)
			if source:
				source = source['object']
			else:
				# force: get all providers in case of resolving for "disabled" preset providers. Or for historic links when the used providers were disabled.
				provider.Provider.initialize(forceAll = True)
				source = provider.Provider.provider(item['provider'].lower(), enabled = False, local = True)['object']

			try:
				# To accomodate Torba's popup dialog.
				u = url = source.resolve(url, internal = internal)
			except:
				u = url = source.resolve(url)

			if resolve == network.Networker.ResolveProvider:
				self.url = url
				return url

			# Allow magnet links and local files.
			#if url == None or not '://' in str(url): raise Exception()
			isLocalFile = ('local' in item and item['local']) or tools.File.exists(url)
			if isLocalFile:
				self.url = url
				return url

			if url == None or (not isLocalFile and not '://' in str(url) and not 'magnet:' in str(url)):
				raise Exception('Error Resolve')

			if not internal:
				metadata = metadatax.Metadata.initialize(source = item, title = item['title'], name = item['file'] if 'file' in item else None, quality = item['quality'])
				item['metadata'] = metadata

			sourceHandler = handler.Handler()
			if handle == None:
				handle = sourceHandler.serviceDetermine(mode = handleMode, item = item, popups = popups)
				if handle == handler.Handler.ReturnUnavailable or handle == handler.Handler.ReturnExternal or handle == handler.Handler.ReturnCancel:
					info = False
					url = None
					raise Exception('Error Handler')

			url = sourceHandler.handle(link = u, item = item, name = handle, download = download, popups = popups, close = handleClose)

			if url == handler.Handler.ReturnUnavailable or url == handler.Handler.ReturnExternal or url == handler.Handler.ReturnCancel:
				info = False
				url = None
				raise Exception('Error Handle')

			if url == False or url == None:
				raise Exception('Error Url')

			# network.Networker.linkIs: for other errors like 'realdebrid'
			if not network.Networker.linkIs(url):
				info = False
				url = None
				raise Exception('Error Service: ' + str(url))

			ext = url.split('?')[0].split('&')[0].split('|')[0].rsplit('.')[-1].replace('/', '').lower()
			extensions = ['rar', 'zip', '7zip', '7z', 's7z', 'tar', 'gz', 'gzip', 'iso', 'bz2', 'lz', 'lzma', 'dmg']
			if ext in extensions:
				if info == True:
					message = interface.Translation.string(33757) % ext.upper()
					interface.Dialog.notification(title = 33448, message = message, icon = interface.Dialog.IconError)
				return None

			try: headers = url.rsplit('|', 1)[1]
			except: headers = ''
			headers = urllib.quote_plus(headers).replace('%3D', '=') if ' ' in headers else headers
			headers = dict(urlparse.parse_qsl(headers))

			if url.startswith('http') and '.m3u8' in url:
				result = client.request(url.split('|')[0], headers=headers, output='geturl', timeout='20')
				if result == None:
					raise Exception('Error m3u8')
			elif url.startswith('http'):
				result = client.request(url.split('|')[0], headers=headers, output='chunk', timeout='20')
				if result == None:
					raise Exception('Error Server')

			if not internal: self.url = url
			return url
		except:
			tools.Logger.error()
			if info == True:
				interface.Dialog.notification(title = 33448, message = 33449, icon = interface.Dialog.IconError)
			return None

	def sourcesDialog(self, items, metadata, handleMode = None):
		try:
			labels = [re.sub(' +', ' ', i['label'].replace(interface.Format.newline(), ' %s ' % interface.Format.separator()).strip()) for i in items]
			choice = control.selectDialog(labels)
			if choice < 0: return ''
			self.playItem(items[choice], metadata = metadata, handleMode = handleMode)
			return ''
		except:
			tools.Logger.error()


	def sourcesDirect(self, items, title, year, season, episode, imdb, tvdb, meta):
		filter = [i for i in items if i['source'].lower() in self.hostcapDict and (i['debrid'] == '' or i['debrid'] == False)]
		items = [i for i in items if not i in filter]

		filter = [i for i in items if i['source'].lower() in self.hostblockDict and (i['debrid'] == '' or i['debrid'] == False)]
		items = [i for i in items if not i in filter]

		items = [i for i in items if ('autoplay' in i and i['autoplay'] == True) or not 'autoplay' in i]
		url = None

		# NB: The progressDialog must be a member variable, otherwise it will be destructed on the end of this function, causing the dialog to hide, before player() shows it again.
		self.progressDialog = None

		try:
			control.sleep(1000)

			heading = interface.Translation.string(33451)
			message = interface.Format.fontBold(interface.Translation.string(33452))
			background = tools.Settings.getInteger('interface.stream.progress') == 1

			self.progressDialog = interface.Dialog.progress(background = background, title = heading, message = message)
			if background: self.progressDialog.update(0, heading, message)
			else: self.progressDialog.update(0, heading)
		except:
			pass

		autoHandler = handler.Handler()
		for i in range(len(items)):

			try:
				if self.progressDialog.iscanceled(): break
			except: pass

			percentage = int(((i + 1) / float(len(items))) * 100)
			if background: self.progressDialog.update(percentage, heading, message)
			else: self.progressDialog.update(percentage, message)
			try:
				if xbmc.abortRequested == True: return sys.exit()
				handle = autoHandler.serviceDetermine(mode = handler.Handler.ModeDefault, item = items[i], popups = False)
				if not handle == handler.Handler.ReturnUnavailable:
					url = self.sourcesResolve(items[i], handle = handle, info = False)
					items[i]['urlresolved'] = url
					if not url == None:
						from resources.lib.modules.player import player
						player().run(title, year, season, episode, imdb, tvdb, url, meta, handle = handle, source = items[i])
						return items[i]
			except:
				pass

		try: self.progressDialog.close()
		except: pass

		interface.Loader.hide() # Always hide if there is an error.
		interface.Dialog.notification(title = 33448, message = 33574, sound = False, icon = interface.Dialog.IconInformation)
		return None


	def errorForSources(self, single = False):
		interface.Loader.hide() # Always hide if there is an error.
		interface.Dialog.notification(title = 33448, message = 32401 if single else 32402, icon = interface.Dialog.IconInformation)


	def getConstants(self):
		self.itemProperty = 'plugin.video.bubbles.container.items'
		self.metaProperty = 'plugin.video.bubbles.container.meta'

		try:
			self.hostDict = handler.HandleUrlResolver().services()
		except:
			self.hostDict = []

		self.hostprDict = ['1fichier.com', 'oboom.com', 'rapidgator.net', 'rg.to', 'uploaded.net', 'uploaded.to', 'ul.to', 'filefactory.com', 'nitroflare.com', 'turbobit.net', 'uploadrocket.net']
		self.hostcapDict = ['hugefiles.net', 'kingfiles.net', 'openload.io', 'openload.co', 'oload.tv', 'thevideo.me', 'vidup.me', 'streamin.to', 'torba.se']
		self.hosthqDict = ['gvideo', 'google.com', 'openload.io', 'openload.co', 'oload.tv', 'thevideo.me', 'rapidvideo.com', 'raptu.com', 'filez.tv', 'uptobox.com', 'uptobox.com', 'uptostream.com', 'xvidstage.com', 'streamango.com']
		self.hostblockDict = []

		self.debridDict = debrid.debridDict()


	def getLocalTitle(self, title, imdb, tvdb, content):
		language = self.getLanguage()
		if not language: return title
		if content.startswith('movie'):
			titleForeign = trakt.getMovieTranslation(imdb, language)
		else:
			titleForeign = tvmaze.tvMaze().getTVShowTranslation(tvdb, language)
		return titleForeign or title


	def getAliasTitles(self, imdb, localtitle, content):
		try:
			localtitle = localtitle.lower()
			language = self.getLanguage()
			titleForeign = trakt.getMovieAliases(imdb) if content.startswith('movie') else trakt.getTVShowAliases(imdb)
			return [i for i in titleForeign if i.get('country', '').lower() in [language, '', 'us'] and not i.get('title', '').lower() == localtitle]
		except:
			return []


	def getLanguage(self):
		if tools.Language.customization():
			language = tools.Settings.getString('scraping.foreign.language')
		else:
			language = tools.Language.Alternative
		return tools.Language.code(language)
