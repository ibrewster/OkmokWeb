from datetime import timedelta, datetime
import psycopg2
from psycopg2.extras import RealDictCursor

from . import app


def correct_station_date(station_timestamp):
    as_str = False
    if type(station_timestamp) == str:
        as_str = True
        station_timestamp = datetime.strptime(station_timestamp, '%Y-%m-%dT%H:%M:%SZ')
    station_year = station_timestamp.year
    target_year = station_year + 1# Initially. May change later.

    if (is_leap_year(station_year) and station_timestamp.month < 3) or \
       (is_leap_year(target_year) and station_timestamp.month >= 3):
        # Special case for target of February 29th (station March 1st)
        # Almost the same, except the date subtraction needs to happen
        # *after* year substitution, not before.
        if station_timestamp.month == 3 and station_timestamp.day == 1:
            station_timestamp = station_timestamp.replace(year=target_year) - timedelta(days=1)
        else:
            station_timestamp -= timedelta(days=1)

            # In the cases where we subtract a day, the year might change.
            target_year = station_timestamp.year + 1

    result = station_timestamp.replace(year=target_year) - timedelta(hours = 1)
    if as_str:
        result = result.strftime('%Y-%m-%dT%H:%M:%SZ')
    return result

def reverse_station_date(target_date):
    target_year = target_date.year
    station_year = target_year - 1  # Initially. May change later.

    target_leap_adjust = is_leap_year(target_year) and target_date.month >= 3
    station_leap_adjust = is_leap_year(station_year) and target_date.month < 3
    is_feb_29 = target_date.month == 2 and target_date.day == 29

    if is_feb_29 or station_leap_adjust or target_leap_adjust:
        if target_date.month == 2 and target_date.day == 28:
            return target_date.replace(year=station_year) + timedelta(days=1)

        target_date += timedelta(days=1)

        # In the cases where we add a day, the year might change
        station_year = target_date.year - 1

    return target_date.replace(year=station_year)


def is_leap_year(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class db_cursor():
    def __init__(self, cursor_factory=None, database = 'carbon', host = "akutan.avo.alaska.edu"):
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
                       database = 'geodesy', host = "akutan.avo.alaska.edu") as cursor:
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
