from datetime import timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

from . import app


class db_cursor():
    def __init__(self, cursor_factory=None, database = 'carbon', host = "akutan.snap.uaf.edu"):
        self._cursor_factory = cursor_factory
        self._db = database
        self._host = host

    def __enter__(self):
        self._conn = psycopg2.connect(host=self._host,
                                      database=self._db,
                                      cursor_factory=self._cursor_factory,
                                      user="geodesy",
                                      password = 'G30dE$yU@F')
        self._cursor = self._conn.cursor()
        return self._cursor

    def __exit__(self, *args, **kwargs):
        try:
            self._conn.rollback()
        except AttributeError:
            return  # No connection
        self._conn.close()


def load_stations():
    # Load station list from DB
    SQL = """
    SELECT
        name,
        latitude::float as lat,
        longitude::float as lng,
        site,
        id as sta_id
    FROM stations
    WHERE name in ('OKCE','OKNC');
    """

    try:
        with db_cursor(cursor_factory = RealDictCursor,
                       database = 'volcano_seismology', host = "137.229.113.120") as cursor:
            cursor.execute(SQL)
            stas = {row['name']: dict(row)
                    for row in cursor}
    except:
        app.logger.exception("Unable to load stations from db")

    return stas


class FetchingDict(dict):
    def __getitem__(self, key):
        if not self:
            print("Loading stations from DB")
            self.update(load_stations())
        return super().__getitem__(key)

    def __contains__(self, item):
        if not self:
            self.update(load_stations())
        return super().__contains__(item)

    def fetch(self):
        self.clear()
        self.update(load_stations())


stations = FetchingDict()
