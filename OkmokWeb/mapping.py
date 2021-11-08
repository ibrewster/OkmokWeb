import csv
import json
import os
import time
import uuid

from datetime import timezone
from io import StringIO

from . import app, compress
from . import utils
from .utils import stations

import ujson
import json
import numpy
import flask
import flask.helpers

from dateutil.parser import parse
from PIL import Image
from psycopg2 import sql

import pandas as pd
import plotly.graph_objects as go


def volc_sort_key(volc):
    name, data = volc
    return data['sort']


@app.route("/")
def _map():
    return flask.render_template("index.html")


def genStationColors(row):
    if row.type == "continuous":
        return "73/0/244"

    if row.type == "campaign":
        return "12/218/59"


@app.route('/gen_graph', methods = ["GET"])
def get_graph_image():
    try:
        date_from = parse(flask.request.args.get('dfrom'))
    except:
        date_from = None

    date_to = parse(flask.request.args['dto'])
    station = flask.request.args['station']
    sensor = flask.request.args['sensor']
    fmt = flask.request.args.get('fmt', 'png')
    width = int(flask.request.args.get('width', 900))

    title = station

    title += ' - '
    data = get_graph_data(False, station=station,
                          sensor = sensor,
                          date_from=date_from, date_to=date_to)

    if not data['dates']:
        return "no data found", 404

    if date_from is None:
        date_from = parse(data['dates'][0] + "T00:00:00Z")

    labels = ['Soil Temp (ºC)', 'WWC-Mineral',
              'WWC-Soilless', 'Dielectric Permittivity']

    if sensor != 'CO2':
        soil_temp = gen_plot_data_dict(data['dates'], data['tempc'])
        wc_mineral = gen_plot_data_dict(data['dates'], data['moisture_mineral'], 2)
        wc_soiless = gen_plot_data_dict(data['dates'], data['moisture_soilless'], 3)
        dialectric_perm = gen_plot_data_dict(data['dates'], data['soil_conductivity'], 4)

        plot_data = [soil_temp, wc_mineral, wc_soiless, dialectric_perm]
        if any(data['electric_cond']):
            elec_conduc = gen_plot_data_dict(data['dates'], data['electric_cond'], 5)
            plot_data.append(elec_conduc)
            labels.append("Electrical Conductivity")

    layout = gen_subgraph_layout(plot_data,
                                 labels,
                                 date_from, date_to)
    sensor_desc = sensor
    if sensor == 1:
        sensor_desc = "bottom"
    elif sensor == 2:
        sensor_desc == "top"

    layout['annotations'] = [{
        "xref": 'paper',
        "yref": 'paper',
        "x": 0.004,
        "xanchor": 'left',
        "y": 1.005,
        "yanchor": 'bottom',
        "text": f"Sensor: {sensor_desc}",
        "showarrow": False,
        "font": {"size": 12}
    }]

    # title += f'{date_from.strftime("%Y-%m-%d")} to {date_to.strftime("%Y-%m-%d")}'
    # layout['title'] = {'text': title,
    # 'x': .115,
    # 'y': .939,
    # 'xanchor': 'left',
    # 'yanchor': 'bottom',
    # 'font': {
    # 'size': 16,
    # }, }
    return gen_graph_image(plot_data, layout, fmt, 'inline',
                           width = width)


def gen_plot_data_dict(x, y, idx=None):
    trace = {
        "x": x,
        "y": y,
        "type": 'scatter',
        "mode": 'markers',
        "marker": {
            "size": 4,
            "color": 'rgb(55,128,256)'
        },
    }

    if idx is not None:
        trace['yaxis'] = f'y{idx}'
        trace['xaxis'] = f'x{idx}'

    return trace


def gen_subgraph_layout(data, titles, date_from, date_to):
    if not isinstance(titles, (list, tuple)):
        titles = [titles, ]

    script_path = os.path.realpath(os.path.dirname(__file__))
    LOGO_PATH = os.path.join(script_path, 'static/img/logos.png')
    logo = Image.open(LOGO_PATH)

    layout = {
        "paper_bgcolor": 'rgba(255,255,255,1)',
        "plot_bgcolor": 'rgba(255,255,255,1)',
        "showlegend": False,
        "margin": {
            "l": 50,
            "r": 25,
            "b": 25,
            "t": 80,
            "pad": 0
        },
        "grid": {
            "rows": len(titles),
            "columns": 1,
            "pattern": 'independent',
            'ygap': 0.05,
        },
        'font': {'size': 12},
        "images": [
            {
                "source": logo,
                "xref": "paper",
                "yref": "paper",
                "x": 1,
                "y": 1.008,
                "sizex": .27,
                "sizey": .27,
                "xanchor": "right",
                "yanchor": "bottom"
            },
        ],
    }

    try:
        x_range = [date_from, date_to]
    except IndexError:
        x_range = None

    for i, title in enumerate(titles):
        if not title:
            continue

        i = i + 1  # We want 1 based numbering here
        y_axis = f'yaxis{i}'
        x_axis = f'xaxis{i}'

        layout[y_axis] = {
            "zeroline": False,
            'title': title,
            'gridcolor': 'rgba(0,0,0,.3)',
            'showline': True,
            'showgrid': False,
            'linecolor': 'rgba(0,0,0,.5)',
            'mirror': True,
            'ticks': "inside"
        }

        layout[x_axis] = {
            'automargin': True,
            'autorange': False,
            'range': x_range,
            'type': 'date',
            'tickformat': '%m/%d/%y<br>%H:%M',
            'hoverformat': '%m/%d/%Y %H:%M:%S',
            'gridcolor': 'rgba(0,0,0,.3)',
            'showline': True,
            'showgrid': False,
            'mirror': True,
            'linecolor': 'rgba(0,0,0,.5)',
            'ticks': "inside"
        }

        if i != len(titles):  # All but the last one
            layout[x_axis]['matches'] = f'x{len(titles)}'
            layout[x_axis]['showticklabels'] = False

    return layout


@app.route('/api/gen_graph', methods=["POST"])
def gen_graph_from_web():
    data = json.loads(flask.request.form['data'])
    layout = json.loads(flask.request.form['layout'])

    # Fix up images in layout (using a URL doesn't seem to work in my testing)
    static_path = os.path.join(app.static_folder, 'img')

    for img in layout['images']:
        img_name = img['source'].split('/')[-1]
        img_path = os.path.join(static_path, img_name)
        img_file = Image.open(img_path)
        img['source'] = img_file

    # Shift the title over a bit
    layout['title']['x'] = .09
    # layout['title']['y'] = .92

    return gen_graph_image(data, layout)


def gen_graph_image(data, layout, fmt = 'pdf', disposition = 'download',
                    width = 900):

    # Change plot types to scatter instead of scattergl. Bit slower, but works
    # properly with PDF output
    for plot in data:
        # We want regular plots so they come out good
        if plot['type'].endswith('gl'):
            plot['type'] = plot['type'][:-2]

    plot_title = layout['title']['text']
    plot_title = plot_title.replace(' ', '_')
    plot_title = plot_title.replace('/', '_')

    args = {'data': data,
            'layout': layout, }

    fig = go.Figure(args)

    # TEMPORARY DEBUG
    #    filename = f"{uuid.uuid4().hex}.pdf"
    #     fig.write_image(os.path.join('/tmp', filename), width = 600, height = 900,
    #                     scale = 1.75)

    # Since we chose 600 for the "width" parameter of the to_image call
    # Adjust the output size by using scale, rather than changing the
    # width/height of the call. Seems to work better for layout.
    scale = min(width / 600, 22)
    fig_bytes = fig.to_image(format = fmt, width = 600, height = 800,
                             scale = scale)
    response = flask.make_response(fig_bytes)
    content_type = f'application/pdf' if fmt == 'pdf' else f'image/{fmt}'
    response.headers.set('Content-Type', content_type)
    if disposition == 'download':
        response.headers.set('Content-Disposition', 'attachment',
                             filename = f"{plot_title}.pdf")
    else:
        response.headers.set('Content-Disposition', 'inline')

    return response


@app.route('/map/download', methods=["POST"])
def gen_map_image():
    # has to be imported at time of use to work with uwsgi
    try:
        import pygmt
    except Exception:
        os.environ['GMT_LIBRARY_PATH'] = '/usr/local/lib'
        import pygmt

    map_bounds = json.loads(flask.request.form['map_bounds'])
    bounds = [map_bounds['west'],
              map_bounds['east'],
              map_bounds['south'],
              map_bounds['north']]

    fig = pygmt.Figure()
    fig.basemap(projection="M16i", region=bounds, frame=('WeSn', 'afg'))

    if bounds[3] > 60:
        grid = '@srtm_relief_15s'
    else:
        grid = '@srtm_relief_01s'

    fig.grdimage(grid, dpi = 600, shading = True)
    fig.coast(rivers = 'r/2p,#00FFFF', water = "#00FFFF", resolution = "f")

    if not stations:
        stations.fetch()

    station_data = pd.DataFrame.from_dict(stations, orient = "index")

    fig.plot(x = station_data.lng, y = station_data.lat,
             style = "c0.5i",
             color = '73/0/244',
             pen = '2p,white')

    fig.text(x = station_data.lng, y = station_data.lat,
             text = station_data.index.tolist(), font = "12p,Helvetica-Bold,white")

    #   fig.show(method = "external")
    save_file = f'{uuid.uuid4().hex}.pdf'
    file_path = os.path.join('/tmp', save_file)
    fig.savefig(file_path)

    file = open(file_path, 'rb')
    file_data = file.read()
    file.close()
    os.remove(file_path)

    response = flask.make_response(file_data)
    response.headers.set('Content-Type', 'application/pdf')
    response.headers.set('Content-Disposition', 'attachment',
                         filename = "MapImage.pdf")

    return response


@app.route('/list_stations')
def list_stations():
    stns = utils.load_stations()
    return flask.jsonify(stns)


@app.route('/get_graph_data')
@compress.compressed()
def get_graph_data(as_json=True, station=None, sensor = None,
                   date_from=None, date_to=None, factor = 100):

    if station is None:
        station = flask.request.args['station']

    if sensor is None:
        sensor = flask.request.args['sensor']

    if date_from is None:
        try:
            date_from = parse(flask.request.args.get('dateFrom'))
            date_from = date_from.replace(tzinfo = timezone.utc, hour = 0,
                                          minute = 0, second = 0, microsecond = 0)
        except (TypeError, ValueError):
            date_from = None

    if date_to is None:
        try:
            date_to = parse(flask.request.args.get('dateTo'))
            date_to = date_to.replace(tzinfo = timezone.utc, hour = 23,
                                      minute = 59, second = 59, microsecond = 9999)
        except (TypeError, ValueError):
            date_to = None

    if factor == "auto":
        span = (date_to - date_from).total_seconds()
        if span > 2592000:  # One month
            factor = 1
        elif span > 1209600:  # two weeks
            factor = 5
        elif span > 604800:  # one week
            factor = 25
        elif span > 172800:  # two days
            factor = 50
        else:
            factor = 100

    else:
        try:
            factor = int(factor)
        except ValueError:
            return flask.abort(422)

    data = load_db_data(station, sensor,
                        factor=factor)

    resp_data = {'factor': factor,
                 'data': data}

    if as_json:
        str_data = ujson.dumps(resp_data)
        return flask.Response(response=str_data, status=200,
                              mimetype="application/json")
    else:
        return data


PERCENT_LOOKUP = {
    1: '90=0',  # Keep every 90th row
    5: '20=0',  # keep every 20th row
    25: '4=0',  # keep every fourth row
    50: '2=0',  # keep every other row
    75: '4>0'  # skip every fourth row
}


@app.route('/get_full_data')
@compress.compressed()
def get_full_data():
    station = flask.request.args['station']
    sensor = flask.request.args['sensor']
    date_from = flask.request.args.get('dateFrom')
    date_to = flask.request.args.get('dateTo')
    filename = f"{station}-{sensor}-{date_from}-{date_to}.csv"

    date_from = parse(date_from).replace(tzinfo = timezone.utc)
    date_to = parse(date_to).replace(tzinfo = timezone.utc)

    data = load_db_data(station, sensor, date_from, date_to)
    # format as a CSV

    del data['info']

    header = []
    csv_data = []
    for col, val in data.items():
        csv_data.append(val)
        if col == "dates":
            col = "date"
        header.append(col)

    csv_data = numpy.asarray(csv_data).T

    csv_file = StringIO()
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(header)
    csv_writer.writerows(csv_data)

    output = flask.make_response(csv_file.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={filename}"
    output.headers["Content-type"] = "text/csv"
    return output


def load_db_data(station, sensor,
                 date_from=None, date_to=None,
                 factor = 100):

    station = station.lower()
    args = []

    dates = '''to_char(date_time,'YYYY-MM-DD"T"HH24:MI:SSZ')'''
    if sensor != 'CO2' and station == 'okce':
        dates = '''to_char(date_time+'1 year'::interval,'YYYY-MM-DD"T"HH24:MI:SSZ')'''

    SQL = f'''SELECT {{fields}}, {dates} as dates FROM {{table}}'''

    if sensor == 'CO2' and station == 'okce':
        fields = ['co2filtered', 'co2raw', 'sensor_temp']
        station = 'okce_only'
    else:
        fields = ['tempc', 'moisture_mineral', 'moisture_soilless', 'soil_conductivity', 'electric_cond']
        SQL += ' WHERE sensor=%s'
        args.append(sensor)

    graph_data = {
        'info': {

        },
    }

    adtl_where = []
    if date_from is not None:
        adtl_where.append("date_time>=%s")
        args.append(date_from)
    if date_to is not None:
        adtl_where.append("date_time<%s")
        args.append(date_to)

    if adtl_where:
        if 'WHERE' not in SQL:
            SQL += ' WHERE '
        else:
            SQL += ' AND '
        SQL += " AND ".join(adtl_where)

    # if factor != 100:
        # print("Running query with factor", factor)
        # postfix = f" AND epoch%%{PERCENT_LOOKUP.get(factor,'1=0')}"
        # SQL += postfix

    SQL += " ORDER BY date_time"

    fields = [sql.Identifier(col) for col in fields]
    data_query = sql.SQL(SQL).format(
        fields = sql.SQL(',').join(fields),
        table = sql.Identifier(station),
    )

    LIMIT_SQL = """
SELECT
    to_char(mintime AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SSZ'),
    to_char(maxtime AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SSZ')
FROM
(SELECT
    min(date_time) as mintime,
    max(date_time) as maxtime
 FROM {table}
) s1;
    """
    limit_query = sql.SQL(LIMIT_SQL).format(table = sql.Identifier(station))

    with utils.db_cursor() as cursor:
        cursor.execute(limit_query, args)
        info = cursor.fetchone()
        graph_data['info']['min_date'] = info[0]
        graph_data['info']['max_date'] = info[1]

        t1 = time.time()
        cursor.execute("SET TIMEZONE='UTC'")
        cursor.execute(data_query, args)
        if cursor.rowcount == 0:
            return graph_data  # No data
        print("Ran query in", time.time() - t1)

        headers = [desc[0] for desc in cursor.description]

        # Return results as a list for each value, rather than records.
        # results = tuple(zip(*cursor.fetchall()))
        t3 = time.time()
        results = pd.DataFrame(cursor.fetchall(), columns = headers)
        print("Got results in", t3 - t1)
        result_dict = results.to_dict('list')
        print("Converted results to dict in", time.time() - t3)
        # graph_data.update(result_dict)
        result_dict.update(graph_data)

        print("processed results in", time.time() - t3)
        print("Got", len(result_dict['dates']), "rows in", time.time() - t1, "seconds")
        return result_dict
