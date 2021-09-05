import sqlite3
import re

DB_FILE = '/Users/cjr/Library/Application Support/Mixxx/mixxxdb.sqlite'


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
    def __init__(self, title, artist, album, genre, duration, comment, filetype, position):
        self.title = title
        self.artist = artist
        self.album = album
        self.genre = genre
        self.duration = duration
        self.comment = comment
        self.filetype = filetype
        self.position = position

    def __str__(self):
        return f'({self.position}). _{self.genre}_  {self.artist} - {self.title} ({self.filetype})'


def create_connection(dbfile=None):
    if dbfile is None:
        dbfile = DB_FILE

    conn = sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    return conn


def match_date(s):
    pattern = re.compile('\d\d\d\d-\d\d-\d\d*')
    return pattern.match(s)


def get_playlists():
    conn = create_connection()
    cursor = conn.cursor()

    sql = 'SELECT id, name, date_created, date_modified FROM Playlists'
    cursor.execute(sql)

    last_playlist = None
    playlists = []
    for row in cursor.fetchall():
        p = Playlist(*row)
        track_sql = """
            SELECT title, artist, album, genre, duration, comment, filetype, position
            FROM PlaylistTracks, Library
            WHERE playlist_id = ?
              AND PlaylistTracks.track_id = Library.id
            ORDER BY position"""

        cursor.execute(track_sql, (p.id,))
        for r in cursor.fetchall():
            p.add_track(Track(*r))

        if match_date(row[1]) and last_playlist is not None:
            last_playlist.add_associated(p)
        else:
            playlists.append(p)
            last_playlist = p

    cursor.close()
    conn.close()
    return playlists


if __name__ == '__main__':
    lst = get_playlists()
    for p in lst:
        print(p)

    p = lst[-1]
    print('-'*80)
    print(p)
    print(len(p.associated))
    for a in p.associated:
        print(a, len(a))

    themax = max(p.associated, key=len)
    print('max associated = ', themax, 'id=', themax.id)

    for t in themax.tracks:
        print(t)


