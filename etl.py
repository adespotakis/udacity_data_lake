import configparser
import logging
import os
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf, monotonically_increasing_id
from pyspark.sql.functions import year, month, dayofmonth, hour, weekofyear, date_format
from typing import Optional

from sql_queries import *


def create_logger(debug_mode: Optional[bool]=False) -> logging.getLogger:
    """
    Self-explanatory, create a logger for streaming output
    :param debug_mode: Is the developer debugging this or no?
    :return: The logging object.
    """
    _logger = logging.getLogger(os.path.basename(__name__))
    _logger.setLevel(logging.INFO if not debug_mode else logging.DEBUG)
    formatter = logging.Formatter('%(filename)s:%(funcName)s:%(levelname)s:%(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    _logger.addHandler(stream_handler)
    return _logger


def create_spark_session():
    spark = SparkSession \
        .builder \
        .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:2.7.0") \
        .getOrCreate()
    return spark


def process_song_data(spark: SparkSession, input_base_path: str, output_base_path) -> None:
    """
    Process the song metadata logs from the designated input path and structure it.
    :param spark: The sparksession object
    :param input_base_path: The base path that holds the ingestable\ data
    :param output_base_path: The base path that details where to save the output.
    :return: None
    """
    song_data = 's3a://udacity-dend/song_data/A/A/*/*.json'
    logger.info("Loading artist and song metadata.")
    logger.warning("Due to overpopulation on the source bucket, only a small subset of song logs will be ingested.")
    df = spark.read.json(song_data)
    logger.info("Done.")
    song_columns = ["song_id", "title", "artist_id", "artist_name", "year", "duration"]
    artist_columns = ["artist_id", "artist_name", "artist_location", "artist_latitude", "artist_longitude"]
    logger.info("Gathering song metadata.")
    song_df = df.select(song_columns).dropDuplicates()
    logger.info("Done.")
    logger.info("Gathering artist metadata.")
    artist_df = df.select(artist_columns).withColumn("id", monotonically_increasing_id())
    artist_df.createOrReplaceTempView("sparkify")
    artist_df = spark.sql(artist_select_distinct)
    logger.info("Done.")
    logger.debug("Creating SQL views for artists and songs dataframes.")
    artist_df.createOrReplaceTempView('artists')  # Will need this for another function.
    song_df.createOrReplaceTempView('songs')  # Ditto.
    logger.debug("Done.")
    logger.info("Writing song dataframe to s3 partitioned by year and artist_name in parquet format.")
    song_df.write.partitionBy(["year", "artist_name"]).format("parquet").mode("overwrite")\
        .save(output_base_path + "songs")
    logger.info("Done.")
    logger.info("Writing artist dataframe to s3 in parquet format.")
    artist_df.write.format("parquet").mode("overwrite").save(output_base_path + "artists")
    logger.info("Done.")


def process_log_data(spark: SparkSession, input_base_path: str, output_base_path: str) -> None:
    """
    Process the user logs from the designated input path and structure it.
    :param spark: The sparksession object
    :param input_base_path: The base path that holds the ingestable\ data
    :param output_base_path: The base path that details where to save the output.
    :return: None
    """
    log_data = input_base_path + 'log_data/*/*/*.json'
    logger.info("Loading user log data.")
    df = spark.read.json(log_data)
    columns = ['userId', 'firstName', 'lastName', 'gender', 'level', 'ts', 'artist', 'song', 'length',
               'location', 'sessionId', 'userAgent']
    log_df = df.select(columns).where(df.page == "NextSong").withColumn("id", monotonically_increasing_id())
    log_df.createOrReplaceTempView("sparkify")
    logger.info("Done.")
    logger.info("Gathering songplay's fact dataframe")
    songplay_df = spark.sql(get_songplay_log_data)
    songplay_df.createOrReplaceTempView('logs')
    get_start_time = udf(lambda x: int(int(x) / 1000))
    get_datetime = udf(lambda x: str(datetime.fromtimestamp(int(x))))
    songplay_df = spark.sql(aggregate_songplay_data).withColumn('start_time', get_start_time('ts'))\
        .withColumn('songplay_id', monotonically_increasing_id()).withColumn("datetime", get_datetime("start_time"))\
        .withColumn("year", year('datetime')).withColumn("month", month('datetime')).drop('datetime', 'ts')
    logger.info("Done.")
    logger.info("Gathering user data.")
    user_df = spark.sql(user_select_distinct)
    logger.info("Done.")
    logger.info("Gathering time data.")
    time_df = songplay_df.select('start_time').dropDuplicates().\
        withColumn("datetime", get_datetime('start_time')).select(
            hour('datetime').alias('hour'),
            dayofmonth('datetime').alias('day'),
            weekofyear('datetime').alias('week'),
            month('datetime').alias('month'),
            year('datetime').alias('year'),
            date_format('datetime', 'E').alias('weekday')
        ).drop('datetime')
    logger.info("Done.")
    logger.info("Writing users dataframe to s3 in parquet format.")
    user_df.write.format("parquet").mode("overwrite").save(output_base_path + "users")
    logger.info("Done.")
    logger.info("Writing time dataframe to s3 partitioned by year and month in parquet format.")
    time_df.write.partitionBy(["year", "month"]).format("parquet").mode("overwrite").save(output_base_path + "time")
    logger.info("Done.")
    logger.info("Writing songplay dataframe to s3 partitioned by year and month in parquet format.")
    songplay_df.write.partitionBy(['year', 'month']).format("parquet").mode("overwrite").\
        save(output_base_path + "songplays")
    logger.info("Done.")


def main() -> None:
    """
    Using Spark, ingest data from some data lake and output the structured data to some other data lake
    :return:
    """
    config = configparser.ConfigParser()
    config.read_file(open('dl.cfg'))
    os.environ['AWS_ACCESS_KEY_ID'] = config['AWS']['AWS_ACCESS_KEY_ID']
    os.environ['AWS_SECRET_ACCESS_KEY'] = config['AWS']['AWS_SECRET_ACCESS_KEY']
    spark = create_spark_session()
    input_data = "s3a://udacity-dend/"
    output_data = "s3a://despotakis-data-lake/"
    process_song_data(spark, input_data, output_data)
    process_log_data(spark, input_data, output_data)


if __name__ == "__main__":
    logger = create_logger()
    main()
