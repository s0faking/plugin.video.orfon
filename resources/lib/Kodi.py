import xbmcaddon
from xbmc import PlayList, PLAYLIST_VIDEO, Player, Keyboard, executebuiltin
from xbmcgui import ListItem, Dialog, DialogProgress
from xbmcaddon import Addon
from xbmcplugin import addDirectoryItem, endOfDirectory, setContent, setResolvedUrl, addSortMethod, SORT_METHOD_VIDEO_TITLE, SORT_METHOD_DATE
import xbmcvfs
import sys
import os
import time
import inputstreamhelper
from urllib.parse import unquote

try:
    from OrfOn import *
except ModuleNotFoundError:
    from resources.lib.OrfOn import *


def translate(translation_id):
    settings = xbmcaddon.Addon()
    translation = settings.getLocalizedString
    return translation(translation_id)


class Kodi:
    version_regex = r"plugin:\/\/([^\/]+)"
    addon_id = re.search(version_regex, sys.argv[0]).groups()[0]
    addon = Addon()
    data_folder = xbmcvfs.translatePath("special://profile/addon_data/%s" % addon_id)

    input_stream_protocol = 'mpd'
    input_stream_drm_version = 'com.widevine.alpha'
    input_stream_mime = 'application/dash+xml'
    input_stream_license_contenttype = 'application/octet-stream'

    geo_lock = False
    max_cache_age = 60*60*24

    def __init__(self, plugin, verbose=False):
        self.verbose = verbose
        self.plugin = plugin
        self.init_storage()
        self.base_path = self.addon.getAddonInfo('path')
        self.resource_path = os.path.join(self.base_path, "resources")
        self.use_subtitles = self.addon.getSetting('useSubtitles') == 'true'
        self.hide_audio_description_content = self.addon.getSetting('hideAD') == 'true'
        self.hide_sign_language_content = self.addon.getSetting('hideOEGS') == 'true'
        self.useragent = self.addon.getSetting('userAgent')
        self.pager_limit = int(self.addon.getSetting('pagerLimit'))

    def init_storage(self):
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)

    @staticmethod
    def execute(command):
        executebuiltin(command)

    def is_geo_locked(self) -> bool:
        return self.geo_lock

    def set_geo_lock(self, lock):
        self.geo_lock = lock

    def hide_content(self, item) -> bool:
        if self.hide_audio_description_content and item.has_audio_description():
            self.log("Hiding %s because AD content hide is enabled in settings" % item.label())
            return True
        if self.hide_sign_language_content and item.has_sign_language():
            self.log("Hiding %s because OEGS content hide is enabled in settings" % item.label())
            return True
        if self.geo_lock and item.is_geo_locked():
            self.log("Hiding %s because GEO Lock is active for your ISP" % item.label())
            return True
        return False

    def render(self, item):
        if not self.hide_content(item):
            if item.is_playable():
                list_item = self.render_video(item)
                link = item.url()
                route = self.plugin.url_for_path(link)
                addDirectoryItem(self.plugin.handle, url=route, listitem=list_item, isFolder=False)
            else:
                list_item = self.render_directory(item)
                link = item.url()
                route = self.plugin.url_for_path(link)
                addDirectoryItem(self.plugin.handle, url=route, listitem=list_item, isFolder=True)

    def restart(self, video):
        self.log("Running Restart Play Action")
        play_item = self.render_video(video)
        streaming_url = video.get_stream().get('url')
        Player().play(streaming_url, play_item)

    def build_stream_url(self, url):
        return "%s|User-Agent=%s" % (url, self.useragent)

    def play(self, videos):
        self.log("Running Play Action")
        playlist = PlayList(PLAYLIST_VIDEO)
        tracks = []
        for video in videos:
            tracks.append(video)

        if len(tracks) > 1:
            for track in tracks:
                play_item = self.render_video(track)
                play_stream = self.build_stream_url(track.get_stream().get('url'))
                playlist.add(play_stream, play_item)
            self.log("Playing Playlist %s from position %d" % (playlist.size(), playlist.getposition()))
        else:
            self.log("Playing Single Video")
            for track in tracks:
                play_item = self.render_video(track)
                setResolvedUrl(self.plugin.handle, True, play_item)
                break

    def render_directory(self, directory) -> ListItem:
        title = directory.label()
        title2 = directory.label2()

        list_item = ListItem(offscreen=True)
        list_item.setContentLookup(False)
        list_item.setLabel(title)
        list_item.setLabel2(title2)
        item_info = self.build_info(directory)
        list_item.setInfo(type="Video", infoLabels=item_info)
        list_item.setIsFolder(not directory.is_playable())
        list_item.setProperty("IsPlayable", str(directory.is_playable()))
        item_art = self.build_art(directory)
        list_item.setArt(item_art)
        return list_item

    def render_video(self, teaser) -> ListItem:
        title = teaser.label()
        title2 = teaser.label2()
        stream_url = self.build_stream_url(unquote(teaser.url()))

        headers = "User-Agent=%s&Content-Type=%s" % (self.useragent, self.input_stream_license_contenttype)
        is_helper = inputstreamhelper.Helper(self.input_stream_protocol, drm=self.input_stream_drm_version)
        if is_helper.check_inputstream():
            list_item = ListItem(path=stream_url, offscreen=True)
            list_item.setContentLookup(False)

            if teaser.get_stream():
                self.log("Found Stream for Video %s" % teaser.label())
                self.log("Stream: (%s)" % teaser.url())
                stream_data = teaser.get_stream()
                list_item.setProperty('inputstream', 'inputstream.adaptive')
                list_item.setProperty('inputstream.adaptive.stream_headers', headers)
                list_item.setProperty('inputstream.adaptive.manifest_type', self.input_stream_protocol)

                if self.use_subtitles and stream_data.get('subtitle') and stream_data.get('subtitle') is not None:
                    list_item.setSubtitles([stream_data.get('subtitle')])
                    list_item.addStreamInfo('subtitle', {'language': 'deu'})

                if stream_data['drm']:
                    self.log("Video %s is DRM protected. Adding DRM relevant parameters" % teaser.label())
                    list_item.setMimeType(self.input_stream_mime)
                    list_item.setProperty('inputstream', 'inputstream.adaptive')
                    list_item.setProperty('inputstream.adaptive.stream_headers', headers)
                    list_item.setProperty('inputstream', is_helper.inputstream_addon)
                    list_item.setProperty('inputstream.adaptive.manifest_type', self.input_stream_protocol)
                    license_url = "%s?BrandGuid=%s&userToken=%s" % (stream_data.get('drm_widewine_url'), stream_data.get('drm_widewine_brand'), stream_data.get('drm_token'))
                    list_item.setProperty('inputstream.adaptive.license_type', self.input_stream_drm_version)
                    list_item.setProperty('inputstream.adaptive.license_key', license_url + '|' + headers + '|R{SSM}|')
            else:
                self.log("No Stream for Video %s (%s)" % (teaser.label(), teaser.url()), 'error')

            list_item.setLabel(title)
            list_item.setLabel2(title2)
            item_info = self.build_info(teaser)

            list_item.setInfo(type="Video", infoLabels=item_info)
            list_item.setIsFolder(not teaser.is_playable())
            list_item.setProperty("IsPlayable", str(teaser.is_playable()))
            video_w, video_h = teaser.get_resolution()
            list_item.addStreamInfo('video', {'aspect': '1.78', 'codec': 'h264', 'width': video_w, 'height': video_h, 'duration': teaser.get_duration()})
            list_item.addStreamInfo('audio', {'codec': 'aac', 'language': 'deu', 'channels': 2})

            item_art = self.build_art(teaser)
            list_item.setArt(item_art)

            context_menu = []
            context_menu_items = teaser.get_context_menu()
            for context_menu_item in context_menu_items:
                context_menu.append(self.build_context_menu(context_menu_item))
            list_item.addContextMenuItems(context_menu, replaceItems=True)
            return list_item
        elif not teaser.get_stream():
            Dialog().notification('No Stream available', 'Unable to find a stream for %s' % title, xbmcaddon.Addon().getAddonInfo('icon'))
        elif not is_helper.check_inputstream():
            Dialog().notification('Inputstream Adaptive not available', 'Install Inputstream Adaptive and Inputstream Helper', xbmcaddon.Addon().getAddonInfo('icon'))

    def build_info(self, item) -> dict:
        desc_prefix = self.build_meta_description(item)
        if desc_prefix is not None and item.get_description():
            generated_description = desc_prefix+item.get_description()
            generated_outline = desc_prefix+self.truncate_string(item.get_description())
        else:
            generated_description = item.get_description()
            generated_outline = self.truncate_string(item.get_description())
        return {
            'title': item.label(),
            'originaltitle': item.label(),
            'sorttitle': item.label(),
            'plot': generated_description,
            'plotoutline': generated_outline,
            'genre': item.genre(),
            'aired': item.date(),
            'country': item.country(),
            'year': item.year(),
            'mediatype': item.media_type()
        }

    @staticmethod
    def select_dialog(title, items):
        select_dialog = Dialog()
        selected = select_dialog.select(title, items)
        if selected != -1:
            return selected
        return False

    @staticmethod
    def build_meta_description(item):
        desc = ""
        meta_desc = item.get_meta_description()
        for label in meta_desc:
            desc += "\n[COLOR blue][LIGHT]%s[/LIGHT][/COLOR] %s" % (label, meta_desc[label])
        if desc != "":
            desc += "\n\n"
        return desc

    def build_art(self, item) -> dict:
        return {
            'clearlogo': item.get_channel_logo(),
            'thumb': item.thumbnail or self.get_media('icon.jpg'),
            'poster': item.poster or self.get_media('poster.jpg'),
            'fanart': item.backdrop or self.get_media('fanart.jpg'),
        }

    def build_context_menu(self, item):
        route = self.plugin.url_for_path(item.get('url'))
        if item.get('type') == 'run':
            return item.get('title'), 'RunPlugin(%s)' % route
        else:
            return item.get('title'), 'Container.Update(%s)' % route

    def list_callback(self, content_type="movies", sort=False) -> None:
        if content_type:
            setContent(self.plugin.handle, content_type)
            # executebuiltin("Container.SetViewMode(51)")
        if sort:
            addSortMethod(int(sys.argv[1]), SORT_METHOD_DATE)
            addSortMethod(int(sys.argv[1]), SORT_METHOD_VIDEO_TITLE)
        endOfDirectory(self.plugin.handle, True)

    def get_media(self, filename):
        return os.path.join(self.resource_path, filename)

    def get_stored_directories(self, storage_key):
        target_file = '%s.json' % storage_key
        self.init_storage()
        json_data = self.load_json(target_file)
        directories = []
        for json_item in json_data:
            directory = Directory(json_item.get('title'), json_item.get('description'), json_item.get('link'))
            directories.append(directory)
        return directories

    def store_directory(self, directory, storage_key):
        target_file = '%s.json' % storage_key
        self.init_storage()

        json_data = self.load_json(target_file)
        directory_json = {
            'title': directory.title,
            'description': directory.description,
            'link': directory.url()
        }

        if json_data:
            json_data.append(directory_json)
        else:
            json_data = [directory_json]
        self.save_json(json_data, target_file)

    @staticmethod
    def truncate_string(str_value, max_len=400) -> str:
        if str_value:
            return str_value[:max_len] + (str_value[max_len:] and ' ...')

    @staticmethod
    def build_url(url, args) -> str:
        arg_str = ""
        for arg in args:
            if not arg_str:
                arg_str = "?%s=%s" % (arg, args.get(arg)[0])
            else:
                arg_str += "&%s=%s" % (arg, args.get(arg)[0])
        return "%s%s" % (url, arg_str)

    @staticmethod
    def get_keyboard_input() -> str:
        keyboard = Keyboard()
        keyboard.doModal()
        if keyboard.isConfirmed():
            return keyboard.getText()
        return ""

    def remove_file(self, file) -> bool:
        file = "%s/%s" % (self.data_folder, file)
        try:
            os.remove(file)
            return True
        except FileNotFoundError:
            self.log("File %s could not be found. Skipping remove action." % file, 'warning')
            return False

    def get_cached_file(self, file) -> tuple:
        channel_map_age = self.get_file_age(file)

        if self.max_cache_age > channel_map_age > 0:
            data = self.load_json(file)
            if not len(data):
                cached = False
            else:
                cached = True
        else:
            self.log("Channel Cache is invalid. Reloading because file age larger than %s seconds (%d seconds)" % (self.max_cache_age, channel_map_age))
            cached = False
            self.remove_file(file)
            data = {}
        return data, cached

    def get_file_age(self, file) -> int:
        file = "%s/%s" % (self.data_folder, file)
        try:
            st = os.stat(file)
            age_seconds = int((time.time() - st.st_mtime)/60)
            self.log("Cache Age %d seconds" % age_seconds)
            return age_seconds
        except FileNotFoundError:
            self.log("File %s could not be found" % file, 'warning')
            return 0

    def save_json(self, json_data, file) -> bool:
        file = "%s/%s" % (self.data_folder, file)
        try:
            with open(file, 'w') as data_file:
                data_file.write(json.dumps(json_data))
            data_file.close()
            return True
        except TypeError:
            self.log("Json file format for %s was invalid. Removing file ..." % file, 'warning')
            os.remove(file)
            return False
        except PermissionError:
            self.log("Permission to File %s was denied" % file, 'warning')
            return False

    def load_json(self, file) -> dict:
        file = "%s/%s" % (self.data_folder, file)
        self.log("Loading JSON from %s" % file)
        try:
            with open(file, 'r') as data_file:
                data = json.load(data_file)
            return data
        except FileNotFoundError:
            self.log("File %s could not be found" % file, 'warning')
            return {}

    def log(self, msg, msg_type='info'):
        if self.verbose:
            print("[%s][ORFON][KODI] %s" % (msg_type.upper(), msg))
