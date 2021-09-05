import sys
sys.path.insert(0, "./libpytunes")

import re
import os
import sqlite3
import pickle

from libpytunes import Library
import audio_metadata
from tinytag import TinyTag
import mutagen

FIND_FLAC = False
WITH_TIMER = True
CORTINA_DURATION = 70
ITUNES_LIBRARY_FILE_LOCATION = "/Users/cjr/Tango/iTunes/iTunes Library.xml"
PICKLE_FILE = 'tangolibrary.pkl'
DB_FILE = '/Users/cjr/Library/Application Support/Mixxx/mixxxdb.sqlite'
CONVERT_LOCATION_PREFIX = [('Volumes/Samsung SSD 860 EVO 500G', '/Users/cjr/Tango')]


CONVERSION_MP3 = {
        'genre': 'TCON',
        'title': 'TIT2',
        'comment': 'COMM::eng',
        'artist': 'TPE1',
        'albumartist': 'TPE2',
        'album': 'TALB',
        'track': 'TRCK'
    }

CONVERSION_M4A = {
        'genre': '\xa9gen',
        'title': '\xa9nam',
        'comment': '\xa9cmt',
        'artist': '\xa9ART',
        'albumartist': 'aART',
        'album': '\xa9alb',
        'track': 'trkn'
    }

# NOTE: we need python < 3.9 as in that version deprecated code from plistlib was removed
#       which is used. See: https://docs.python.org/3/library/plistlib.html

# Usage tip for displaying colours:
#   less -R
#   grep --color=always


class bcolors:
    TANDA = '\033[95m'
    MILONGA = '\033[94m'
    VALS = '\033[96m'
    TANGO = '\033[92m'
    CORTINA = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def min_sec(secs):
    if secs is not None:
        m, s = divmod(secs, 60)
        m = int(m)
        s = int(s)
        if m > 59:
            h, m = divmod(m, 60)
            h = int(h)
            m = int(m)
            return f'{h}:{m:02d}:{s:02d}'
        else:
            return f'{m}:{s:02d}'
    else:
        return '_:__'


def colorise_genre(genre, message=None):
    lowgenre = genre.lower() if genre is not None else ''
    if compare_genre(genre, 'tango'):
        wrap = bcolors.TANGO
    elif compare_genre(genre, 'milonga'):
        wrap = bcolors.MILONGA
    elif compare_genre(genre, 'valse'):
        wrap = bcolors.VALS
    elif compare_genre(genre, 'cortina') or compare_genre(genre, 'silent'):
        wrap = bcolors.CORTINA
    else:
        wrap = bcolors.FAIL
    if message is None:
        message = genre
    return f'{wrap}{bcolors.BOLD}{message}{bcolors.ENDC}'


def normalize_genre(genre):
    low_genre = genre.lower()
    if low_genre.startswith('vals'):
        return 'Vals'
    elif low_genre.find('tango') >= 0:
        return 'Tango'
    elif low_genre.startswith('milong') or low_genre == 'candombe' or low_genre.startswith('fox'):
        return 'Milonga'
    elif low_genre in ['cortina', 'electronica', 'easy listening', 'r & b', 'r&b',
                       'wereld', 'alternative & punk', 'classical', 'sounds', 'cancion', 'marcha',
                       'guaracha', 'polka', 'ritmos varios']:
        return 'Cortina'
    elif low_genre == 'silent':
        return 'Silent'
    elif low_genre == 'cumparsita':
        return 'Cumparsita'
    else:
        return genre


def compare_genre(genre, value):
    """Check if a genre equals a value for a genre"""
    return normalize_genre(genre) == normalize_genre(value)


def oldcompare(genre, value):
    genre = genre.lower() if genre is not None else ''
    if value is not None:
        value = normalize_genre(value)
        if value == 'Vals':
            return normalize_genre(genre) == 'Vals'
        elif value == 'Milonga':
            return genre.startswith('milong') or genre == 'candombe' or genre == 'foxtrot'
        elif value == 'Tango':
            return genre == 'Tango'
        elif value == 'Cortina':
            return genre == 'Cortina'
        elif value == 'Silent':
            return genre == 'Silent'
        elif value == 'Cumparsita':
            return genre == 'Cumparsita'
        elif value == 'unknown':
            return not compare_genre(genre, 'milonga') \
                    and not compare_genre(genre, 'valse') \
                    and not compare_genre(genre, 'tango') \
                    and not compare_genre(genre, 'cortina') \
                    and not compare_genre(genre, 'silent') \
                    and not compare_genre(genre, 'cumparsita')
        else:
            return False
    else:
        return False


def mutagen_to_dict(metadata, filetype='m4a'):
    #print(metadata.keys())
    #print(metadata)
    if filetype == 'm4a':
        conversion = CONVERSION_M4A
    elif filetype == 'mp3':
        conversion = CONVERSION_MP3

    for k in metadata.keys():
        if k.startswith('COMM'):
            conversion['comment'] = k
            break
    d = {}
    for k,v in conversion.items():
        if v in metadata.keys():
            val = metadata[v]
            if type(val) == list:
                val = val[0]
            d[k] = val
        else:
            #print(f"mutagen_to_dict: {v} missing from metadata")
            d[k] = None
    return d


class TangoLibrary(object):
    def __init__(self, playlists=[]):
        self.playlists = playlists

    def __len__(self):
        return len(self.playlists)

    def __str__(self):
        return f"Tango Library: {len(self.playlists)} playlists"

    def display(self):
        display_playlists(self.playlists)

    def dump(self, filename):
        with open(filename, 'wb') as f:
            pickle.dump(self.playlists, f)

    @staticmethod
    def load(filename):
        with open(filename, 'rb') as f:
            playlists = pickle.load(f)
        return TangoLibrary(playlists)


class Playlist(object):
    def __init__(self, id, name, date_created, date_modified):
        self.id = id
        self.name = name
        self.date_created = date_created
        self.date_modified = date_modified
        self.associated = []
        self.tracks = []

    def add_associated(self, playlist):
        self.associated.append(playlist)

    def add_track(self, track):
        self.tracks.append(track)

    def __str__(self):
        associated_indicator = f'(+{len(self.associated)})' if self.associated else ''
        track_indicator = f'[*{len(self.tracks)}]'
        return f'{self.name} - {self.date_modified} {associated_indicator} {track_indicator}'

    def __len__(self):
        return len(self.tracks)


class Track(object):
    def __init__(self, title, artist, album, genre, duration, comment, filetype, location, position):
        self.title = title
        self.artist = artist
        self.album = album
        self.genre = genre if genre is not None else 'unknown'
        self.duration = duration
        self.comment = comment
        self.filetype = filetype

        for bad_location, good_location in CONVERT_LOCATION_PREFIX:
            if location.startswith(bad_location):
                self.location = location.replace(bad_location, good_location)
            else:
                self.location = location

        self.position = position
        self.has_flac = False
        self.updated = []

        self.location_exists = os.path.exists(self.location)
        if not self.location_exists:
            print(f'{bcolors.FAIL}Location {self.location} does not exist{bcolors.ENDC}')
        else:
            self._update_from_metadata()

    def _update_from_metadata(self):
        """Update track data based on the metadata of the audio file"""
        if self.filetype.lower() in ['flac', 'wav']:
            self._update_from_metadata_audiofile()
        elif self.filetype.lower() in ['m4a', 'mp3']:
            self._update_from_metadata_mutagen(filetype=self.filetype.lower())
        else:
            print(f"{bcolors.FAIL}GOT unknown filetype {self.filetype}{bcolors.ENDC}")

    def _update_from_metadata_tinytag(self):
        """Update metadata using 'tinytag' library"""
        metadata = TinyTag.get(self.location)
        if metadata.genre and self.genre != metadata.genre:
            self.updated.append(('genre', self.genre, metadata.genre))
            self.genre = metadata.genre
        if metadata.title and self.title != metadata.title:
            self.updated.append(('title', self.title, metadata.title))
            self.title = metadata.title
        print(metadata)

    def _update_from_metadata_audiofile(self):
        """Update metadata using 'metadata_audiofile' library"""
        def get_tag(metadata, field):
            out = None
            if field in metadata['tags'].keys() and metadata['tags'][field]:
                l = metadata['tags'][field]
                if type(l) == list:
                    if len(l) > 0:
                        out = l[0]
                else:
                    out = l
            #print(f'get_tag(metadata, {field}) = {out}')
            return out

        #print(f"{self.filetype}: using audiofile")
        metadata = audio_metadata.load(self.location)
        #print(metadata)
        if 'genre' in metadata['tags'].keys() and self.genre != get_tag(metadata, 'genre'):
            if get_tag(metadata, 'genre') == 'Samba' and self.location.endswith('mp3'):
                print(f'{bcolors.FAIL}Got samba{bcolors.ENDC}')
                print(metadata)
                self._update_from_metadata_mutagen(filetype='mp3', show_metadata=True)
            else:
                self.updated.append((f'{self.filetype}: genre', self.genre, get_tag(metadata, 'genre')))
                self.genre = get_tag(metadata, 'genre')

        if 'title' in metadata['tags'].keys() and metadata['tags']['title'] and \
                self.title != get_tag(metadata, 'title'):
            self.updated.append((f'{self.filetype}: title', self.title, get_tag(metadata, 'title')))
            self.title = get_tag(metadata, 'title')
        if 'artist' in metadata['tags'].keys() and metadata['tags']['artist'] and \
                self.artist != get_tag(metadata, 'artist'):
            self.updated.append((f'{self.filetype}:artist', self.artist, get_tag(metadata, 'artist')))
            self.title = get_tag(metadata, 'artist')
        #print(metadata)

    def _update_from_metadata_mutagen(self, filetype='m4a', show_metadata=False):
        """Update metadata using 'mutagen' library"""
        mutagen_metadata = mutagen.File(self.location)

        #print(f'm4a: {self.artist} - {self.title} (mutagen)')
        #print(mutagen_metadata.pprint())

        metadata = mutagen_to_dict(mutagen_metadata, filetype=filetype)

        if show_metadata:
            print(filetype, metadata)

        if metadata['genre'] and self.genre != metadata['genre']:
            self.updated.append((f'{filetype}: genre', self.genre, metadata['genre']))
            print(f"{bcolors.FAIL}{self.filetype}: updating genre for {self.artist} - '{self.title}' "+
            f"from {self.genre} to {metadata['genre']}{bcolors.ENDC}")
            self.genre = str(metadata['genre'])
            if type(self.genre) != type(''):
                print(f'{bcolors.FAIL}GENRE type fail, got {self.genre} {type(self.genre)}{bcolors.ENDC}')
                print(metadata)
        if metadata['title'] and self.title != metadata['title']:
            self.updated.append((f'{self.filetype}: title', self.title, metadata['title']))
            self.title = str(metadata['title'])
        if metadata['artist'] and self.artist != metadata['artist']:
            self.updated.append((f'{self.filetype}: artist', self.artist, metadata['artist']))
            self.artist = str(metadata['artist'])
        #print(metadata)

    def __len__(self):
        return self.duration

    def __str__(self):
        return f'({self.position}). _{self.genre}_  {self.artist} - {self.title} ({self.filetype})'


class Tanda(object):
    def __init__(self):
        self.generated_name = None
        self.tracks = []
        self.total_time = 0
        self.genre = None
        self.artist_category = None

    def add_track(self, track):
        if len(self.tracks) == 0:
            self.genre = normalize_genre(track.genre)
            self.generated_name = track.artist
        self.tracks.append(track)
        self.total_time += track.duration

    def __len__(self):
        return len(self.tracks)

    def __str__(self):
        s = f'*** [{min_sec(self.total_time)}] {self.genre} {self.generated_name} ***\n'
        return s


def create_connection(dbfile=None):
    if dbfile is None:
        dbfile = DB_FILE

    conn = sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    return conn


def match_date(s):
    pattern = re.compile('\d\d\d\d-\d\d-\d\d*')
    return pattern.match(s)


def find_flac_version(track):
    res = False
    conn = create_connection()
    cursor = conn.cursor()

    sql = """
        SELECT title, artist, album, genre, duration, comment, filetype, location
        FROM Library
        WHERE title LIKE ? AND album LIKE ?"""
    cursor.execute(sql, (f'{track.title}%', f'{track.album}%'))
    rows = cursor.fetchall()
    if len(rows) > 0:
        for r in rows:
            r += (0,)
            t = Track(*r)
            if t.filetype == 'flac':
                #print("Found FLAC version for the following track:")
                #print(f'{track.filetype}', track)
                #print("FLAC: ", t)
                res = True
                break

    cursor.close()
    conn.close()

    return res


def get_mixxx_playlists(query=None, embed=True):
    conn = create_connection()
    cursor = conn.cursor()

    sql = 'SELECT id, name, date_created, date_modified FROM Playlists'
    cursor.execute(sql)

    last_playlist = None
    playlists = []
    for row in cursor.fetchall():
        p = Playlist(*row)
        track_sql = """
            SELECT title, artist, album, genre, duration, comment, filetype, track_locations.location, position
            FROM PlaylistTracks, library, track_locations
            WHERE playlist_id = ?
              AND PlaylistTracks.track_id = Library.id
              AND library.location = track_locations.id
            ORDER BY position"""

        cursor.execute(track_sql, (p.id,))
        for r in cursor.fetchall():
            t = Track(*r)
            if FIND_FLAC and t.filetype != 'flac':
                t.has_flac = find_flac_version(t)
            p.add_track(t)

        if embed and match_date(row[1]) and last_playlist is not None:
            last_playlist.add_associated(p)
        else:
            playlists.append(p)
            last_playlist = p

    cursor.close()
    conn.close()

    # Only at the end we filter for the query
    if query is not None:
        print("query= ", query)
        matcher = re.compile(query)
        playlists = list(filter(lambda x: matcher.match(x.name), playlists))
        # FIXME: Don't use regex for now
        print("got ",len(playlists), "returns")
        #playlists = list(filter(lambda x: x.name == query, playlists))

    return playlists


def read_itunes(query=None):
    def filetype(loc):
        """file name's extension is filetype"""
        return loc[loc.rindex('.')+1:]

    l = Library(ITUNES_LIBRARY_FILE_LOCATION)

    playlist_names = l.getPlaylistNames()
    if query is not None:
        matcher = re.compile(query)
        playlist_names = list(filter(lambda x: matcher.match(x), playlist_names))

    playlists = []
    for i, playlist_name in enumerate(playlist_names):
        p_itunes = l.getPlaylist(playlist_name)
        # name, playlist_id, tracks
        p = Playlist(p_itunes.playlist_id, p_itunes.name, None, None)
        position = 1
        for t in p_itunes.tracks:
            # Note that iTunes has its time in milliseconds
            track = Track(t.name, t.artist, t.album, t.genre, t.total_time // 1000, t.comments, filetype(t.location), t.location, position)
            if FIND_FLAC and track.filetype != 'flac':
                track.has_flac = find_flac_version(track)
            p.add_track(track)
            position += 1
        #prev_genre = None
        #tango_counter = 0
        #for t in p.tracks:
            # do something with tracks
            # print('do something with tracks')

        playlists.append(p)

    # Only at the end we filter for the query
    if query is not None:
        matcher = re.compile(query)
        playlists = list(filter(lambda x: matcher.match(x.name), playlists))

    return playlists


def itunes_main():
    orig_lst = read_itunes()
    playlists = list(filter(lambda x: x.name.startswith('Riga'), orig_lst))
    return playlists


def playlist_to_tandas(playlist):
    tandas = []
    prev_track = None
    cur_tanda = Tanda()
    tango_counter = 0
    prev_genre = None
    for t in playlist.tracks:
        lowgenre = t.genre.lower() if t.genre is not None else ''
        ignore_genre_change = False
        if compare_genre(lowgenre, 'tango'):
            tango_counter += 1
        elif tango_counter > 1 and compare_genre(lowgenre, 'unknown'):
            tango_counter += 1
            ignore_genre_change = True
        else:
            tango_counter = 0

        if prev_track is None:
            # print(f"{prev_track.genre}  -- compare {t.genre} / {prev_track.genre}")
            cur_tanda.add_track(t)
        #elif compare_genre(t.genre, prev_track.genre) or ignore_genre_change:
        elif compare_genre(t.genre, prev_genre) or ignore_genre_change:
            if tango_counter > 4:
                tango_counter = 1
                tandas.append(cur_tanda)
                cur_tanda = Tanda()
            cur_tanda.add_track(t)

        else:
            tandas.append(cur_tanda)
            cur_tanda = Tanda()
            if compare_genre(t.genre, 'tango'):
                tango_counter = 1
            else:
                tango_counter = 0
            cur_tanda.add_track(t)
        prev_track = t

        if ignore_genre_change:
            # prev_genre = 'tango'
            pass
        elif t.genre is not None:
            prev_genre = t.genre.lower()
        else:
            prev_genre = ''


    # clean up
    if len(cur_tanda) > 0:
        tandas.append(cur_tanda)

    return tandas


def display_tandas(tandas):
    for tanda in tandas:
        if tanda.genre.lower() == 'silent':
            s = f'\t\t{"."*7}{tanda.tracks[0].title}{"."*7}\n'
        elif tanda.genre.lower() == 'cortina':
            s = ''
            for t in tanda.tracks:
                s += f'\t\t{"="*7} {t.artist} - {t.title} {"="*7}\n'
        elif tanda.tracks[0].title.lower().startswith('la cumparsita'):
            s = f'\t\t{bcolors.CORTINA}{bcolors.BOLD}{"#"*7} {tanda.tracks[0].title} - {tanda.tracks[0].artist} {"#"*7}{bcolors.ENDC}\n'
        else:
            s = f'*** [{min_sec(tanda.total_time)}] {colorise_genre(tanda.genre)} {bcolors.BOLD}{tanda.generated_name}{bcolors.ENDC} ***\n'
            for t in tanda.tracks:
                s += f'\t\t{t.position} .. {t.title} ({t.filetype}{f"|{bcolors.FAIL}FLAC{bcolors.ENDC}" if t.has_flac else ""}) [{min_sec(t.duration)}] {t.updated}\n'
        print(s)


def display_playlists_orig(playlists, query=None, timer=None):
    if timer is None:
        timer = WITH_TIMER
    demarcation = 100
    total_time = 0
    for p in playlists:
        print('\n')
        print('='*demarcation)
        print(f'\t{bcolors.TANDA}{p.name}{bcolors.ENDC}')
        print('='*demarcation)
        prev_genre = None
        tango_counter = 0
        for t in p.tracks:
            lowgenre = t.genre.lower() if t.genre is not None else ''
            ignore_genre_change = False
            if compare_genre(lowgenre, 'tango'):
                tango_counter += 1
            elif tango_counter > 1 and compare_genre(lowgenre, 'unknown'):
                tango_counter += 1
                ignore_genre_change = True
            else:
                tango_counter = 0

            if prev_genre is not None and not compare_genre(lowgenre, prev_genre) and not ignore_genre_change:
                prefix = '-'*demarcation + '\n'
            else:
                prefix = ''

            if ignore_genre_change:
                #prev_genre = 'tango'
                pass
            elif t.genre is not None:
                prev_genre = t.genre.lower()
            else:
                prev_genre = ''

            if tango_counter > 4:
                prefix = '-'*demarcation + '\n'
                tango_counter = 1

            stars_for_playlist_name = ' ' * (len(p.name) + 2)

            if lowgenre == 'cortina' or lowgenre == 'silent':
                if timer:
                    total_time += CORTINA_DURATION  # 70 seconds for cortina
                    cortina_duration_prefix = '+' + min_sec(CORTINA_DURATION)  # + '/' + min_sec(total_time)
                    stars_for_playlist_name = ' ' * ((len(p.name) + 2) - len(cortina_duration_prefix))
                else:
                    cortina_duration_prefix = ''
                print(f'{prefix}\t{cortina_duration_prefix}{stars_for_playlist_name} *{colorise_genre(t.genre)}* {t.artist} -- {t.title}')

            elif t.title == 'La Cumparsita':
                print(f'{prefix}\t{stars_for_playlist_name} ***{bcolors.TANDA}cumparsita{bcolors.ENDC}*** {t.artist} -- {t.title}')
                print('-'*demarcation)
                # Don't show anything after 'La Cumparsita' as it hasn't been actually played
                # unless 'query' is set
                if query is None:
                    break
            else:

                location_warning = ''
                if t.location.startswith('/Volumes/Samsung'):
                    location_warning = f'{bcolors.FAIL}#BAD LOC#{bcolors.ENDC}'

                if timer:
                    total_time += t.duration
                    timer_prefix = min_sec(total_time)
                else:
                    timer_prefix  = ''
                print(f'{prefix}\t{timer_prefix}\t{p.name}:  _{colorise_genre(t.genre)}_ {t.artist} -- {t.title} ({t.filetype}{f"|{bcolors.FAIL}FLAC{bcolors.ENDC}" if t.has_flac else ""}) [{min_sec(t.duration)}]{location_warning}')


def display_playlists(playlists, query=None, timer=None):
    if timer is None:
        timer = WITH_TIMER
    demarcation = 100
    total_time = 0
    for p in playlists:
        tandas = playlist_to_tandas(p)
        total_time = 0
        num_tandas = 0
        for t in tandas:
            if t.genre.lower() == 'cortina':
                total_time += CORTINA_DURATION
            else:
                num_tandas += 1
                for track in t.tracks:
                    total_time += track.duration
        # display playlist title
        print('\n')
        print('='*demarcation)
        print(f'\t{bcolors.TANDA}{p.name}{bcolors.ENDC} ({num_tandas} tandas, {min_sec(total_time)} total time)')
        print('='*demarcation)

        # display tandas of playlist
        display_tandas(tandas)


def mixxx_main(query=None, timer=None, embed=None):
    orig_lst = get_mixxx_playlists(query=query, embed=embed)
    playlists = []
    for p in orig_lst:
        if p.associated:
            themax = max(p.associated, key=len)
            if len(themax) > 0:
                themax.name = p.name
                playlists.append(themax)
            else:
                playlists.append(p)
        else:
            playlists.append(p)

    return playlists


def test_audio_libraries():
    file = '/Users/cjr/Tango/iTunes/iTunes Music/Music/Francisco Canaro/Candombe (1941-1949)/04 El lloron-Ernesto Fama[Contracanto por coro].mp3'
    print("audio metadata")
    metadata = audio_metadata.load(file)
    print(metadata)

    print("tinytag")
    metadata = TinyTag.get(file)
    print(metadata)

    print("mutagen")
    metadata = mutagen.File(file)
    print(metadata['TCON'])


if __name__ == '__main__':
    #itunes_main()
    #print(compare_genre('milonga', 'unknown'))
    #playlists = mixxx_main(query='Vilnius marathon 2021.08.28.28', timer=True, embed=False)
    #playlists = mixxx_main(query='2021-08-28 \(2\)', timer=True, embed=False)
    #playlists = mixxx_main(query='Ziggis.*', timer=True, embed=False)

    #display_playlists(playlists, query=query, timer=timer)
    playlists = read_itunes(query='^.*Event 4.*$')
    library = TangoLibrary(playlists)
    #for p in playlists:
    #    print(p.name)
    #    tandas = playlist_to_tandas(playlists[0])
    #    display_tandas(tandas)
    #display_playlists(playlists)
    #library.display()

    #library.dump(PICKLE_FILE)

    #library = TangoLibrary.load(PICKLE_FILE)
    library.display()




