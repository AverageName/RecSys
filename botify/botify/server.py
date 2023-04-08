import json
import logging
import time
from dataclasses import asdict
from datetime import datetime

from flask import Flask
from flask_redis import Redis
from flask_restful import Resource, Api, abort, reqparse
from gevent.pywsgi import WSGIServer

from botify.data import DataLogger, Datum
from botify.experiment import Experiments, Treatment
from botify.recommenders.random import Random
from botify.recommenders.sticky_artist import StickyArtist
from botify.recommenders.toppop import TopPop
from botify.recommenders.indexed import Indexed
from botify.recommenders.contextual import Contextual
from botify.track import Catalog

import numpy as np

root = logging.getLogger()
root.setLevel("INFO")

app = Flask(__name__)
app.config.from_file("config.json", load=json.load)
api = Api(app)

# TODO Seminar 6 step 3: Create redis DB with tracks with diverse recommendations
tracks_redis = Redis(app, config_prefix="REDIS_TRACKS")
tracks_my_redis = Redis(app, config_prefix="REDIS_TRACKS_MINE")
artists_redis = Redis(app, config_prefix="REDIS_ARTIST")
recommendations_redis = Redis(app, config_prefix="REDIS_RECOMMENDATIONS")

data_logger = DataLogger(app)

# TODO Seminar 6 step 4: Upload tracks with diverse recommendations to redis DB
catalog = Catalog(app).load(
    app.config["TRACKS_CATALOG"], app.config["TOP_TRACKS_CATALOG"]
)
catalog.upload_tracks(tracks_redis.connection)
catalog.upload_artists(artists_redis.connection)
catalog.upload_recommendations(recommendations_redis.connection)

my_catalog = Catalog(app).load(
    app.config["TRACKS_CATALOG_MINE"], app.config["TOP_TRACKS_CATALOG"]
)
my_catalog.upload_tracks(tracks_my_redis.connection)
my_catalog.upload_artists(artists_redis.connection)
my_catalog.upload_recommendations(recommendations_redis.connection)

parser = reqparse.RequestParser()
parser.add_argument("track", type=int, location="json", required=True)
parser.add_argument("time", type=float, location="json", required=True)


class Hello(Resource):
    def get(self):
        return {
            "status": "alive",
            "message": "welcome to botify, the best toy music recommender",
        }


class Track(Resource):
    def get(self, track: int):
        data = tracks_redis.connection.get(track)
        if data is not None:
            return asdict(catalog.from_bytes(data))
        else:
            abort(404, description="Track not found")


class NextTrack(Resource):
    def post(self, user: int):
        start = time.time()

        args = parser.parse_args()

        # TODO Seminar 6 step 6: Wire RECOMMENDERS A/B experiment
        treatment = Experiments.CONTEXTUALVSCONTEXTUAL.assign(user)
        # if treatment == Treatment.T1:
        #     recommender = StickyArtist(tracks_redis.connection, artists_redis.connection, catalog)
        # elif treatment == Treatment.T2:
        #     recommender = TopPop(tracks_redis.connection, catalog.top_tracks[:100])
        # elif treatment == Treatment.T3:
        #     recommender = Indexed(tracks_redis.connection, recommendations_ub_redis.connection, catalog)
        # elif treatment == Treatment.T4:
        #     recommender = Indexed(tracks_redis.connection, recommendations_redis.connection, catalog)
        if treatment == Treatment.T1:
            recommender = Contextual(tracks_my_redis.connection, my_catalog)
        else:
            recommender = Contextual(tracks_redis.connection, catalog)

        recommendation = recommender.recommend_next(user, args.track, args.time)

        data_logger.log(
            "next",
            Datum(
                int(datetime.now().timestamp() * 1000),
                user,
                args.track,
                args.time,
                time.time() - start,
                recommendation,
            ),
        )
        return {"user": user, "track": recommendation}


class LastTrack(Resource):
    def post(self, user: int):
        start = time.time()
        args = parser.parse_args()
        data_logger.log(
            "last",
            Datum(
                int(datetime.now().timestamp() * 1000),
                user,
                args.track,
                args.time,
                time.time() - start,
            ),
        )
        return {"user": user}


api.add_resource(Hello, "/")
api.add_resource(Track, "/track/<int:track>")
api.add_resource(NextTrack, "/next/<int:user>")
api.add_resource(LastTrack, "/last/<int:user>")


if __name__ == "__main__":
    http_server = WSGIServer(("", 5000), app)
    http_server.serve_forever()
