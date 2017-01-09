#!/usr/bin/env python
"""Cleans up a directory of speed data into a single CSV file ready for analysis

Author: Andrew Clarry
Date: 15/06/16
"""

import os
import datetime as dt

import numpy as np
import pandas as pd
from sklearn.preprocessing import Imputer
from sklearn.neighbors import KernelDensity

DATA_DIR = "Data"
EMME_VOLUME_DATA = os.path.join(DATA_DIR, "EMME 2011 VOLUME SUMMARY.OCT2015.v2.csv")
EMME_LINK_DATA = os.path.join(DATA_DIR, "EMME_link_data.csv")
RAW_DATA_DIR = os.path.join(DATA_DIR, "Geoprocessed Data", "Processed CSVs")
CLEANED_DATA_DIR = os.path.join(DATA_DIR, "Cleaned Data")


def clean_trips(directory_name, cache_file=None, clean_users=True):
    """Returns a Pandas dataframe of cleaned, aggregated trips from a directory.
    """

    csv_list = [os.path.join(directory_name, f) for f in os.listdir(directory_name) 
                if os.path.splitext(f)[1] == ".csv"]
    print("Reading in data")
    df_list = [pd.read_csv(csv, parse_dates=["STARTED_AT"])
               for csv in csv_list]
    print("Cleaning trips")
    data = pd.concat([clean_trip(d) for d in df_list])
    data = clean_data(data, clean_users=clean_users)
    print("Writing cleaned data to %s" % cache_file)
    data.to_csv(cache_file, encoding="utf8")
    print("Successfully wrote data to csv")


def clean_trip(df):
    """Cleans a pandas dataframe corresponding to a single trip"""
    df = df[df["CUMUL_METE"] != 0]
    df['trip_length'] = df['CUMUL_METE'].max()
    df.loc[df["SIG_DIST"] < 0, "SIG_DIST"] = 1000
    return df


def add_bike_code(df):
    """Adds bike facility information to the data frame"""
    df['bike_lanes'] = df['BIKE_CODE'] == 11
    df['sharrows'] = df['BIKE_CODE'].isin((3, 4))
    df['bike_path'] = df['BIKE_CODE'].isin((6, 7))
    return df


def add_route_stats(df):
    """Adds information about the individual link"""
    df['SLOPE_TF'] = df['SLOPE_TF'] * df['LINK_DIR'] * (-1)
    return df


def add_emme_volume_stats(df, emme_volume_csv):
    volume_df = pd.read_csv(emme_volume_csv)
    
    same_dir = df["LINK_DIR"] == 1
    df.loc[same_dir, "EMME_ID"] = df.loc[same_dir, "EMME_MATCH"]
    df.loc[~same_dir, "EMME_ID"] = df.loc[~same_dir, "EMME_CONTR"]
    # Add volume info for each point
    df = pd.merge(df, volume_df, left_on="EMME_ID", right_on="LINK_ID", how="left")

    time_categories = (("AM_VOL", 6, 10),
                       ("MID_VOL", 10, 16),
                       ("PM_VOL", 16, 19),
                       ("EVE_VOL", 19, 6))
    dt_index = pd.DatetimeIndex(df["RECORDED_A"])
    for period, start, stop in time_categories:
        df[period] = df[period].fillna(0)
        if start < stop:
            index = (start <= dt_index.hour) & (dt_index.hour < stop)
        else:
            index = (start <= dt_index.hour) | (dt_index.hour < stop)
        df.loc[index, "volume"] = df.loc[index, period]
    return df


def add_emme_stats(df, emme_volume_csv=EMME_VOLUME_DATA, emme_link_csv=EMME_LINK_DATA):
    """Adds information from the corresponding EMME link"""

    print("Reading emme volume csv")
    df = add_emme_volume_stats(df, emme_volume_csv)
            
    print("Reading emme link csv")
    link_df = pd.read_csv(emme_link_csv)
    LINK_INFO_COLS = ["ID", "DATA2", "LANES", "VDF"]
    
    # Add link info for each point
    df = pd.merge(df, link_df.loc[:, LINK_INFO_COLS], left_on="EMME_ID", right_on="ID", how="left")
    df["speed_limit"] = df["DATA2"]
    df.drop("DATA2", axis=1, inplace=True)
    
    df.loc[df.volume == 0, "volume"] = 0
    df.loc[df.VDF == 0, "VDF"] = 90
    df.loc[df.LANES == 0, "LANES"] = 1
    df.loc[df.speed_limit == 0, "speed_limit"] = 40
    
    df.loc[df["EMME_ID"].isin(("", " ")), ("volume", "speed_limit", "LANES", "VDF")] = (0, 40, 2, 90) 

    return df


def estimate_user_age_dist(df, bandwidth=0.2):
    """Converts the users age to a continuous variable
    
    Uses a gaussian kernel to create a kernel density estimate of the age
    distribution, so that ages can be sampled from the age ranges more correctly.
    Returns a numpy array representing the distribution.
    """
    ranges = ((1, 0, 18), (2, 18, 25), (3, 25, 35), 
              (4, 35, 50), (5, 50, 65), (6, 65, 85))
    age_samples = np.concatenate(
            [np.random.uniform(lower, upper, (df['AGE'] == ind).sum()) 
                for ind, lower, upper in ranges])
    age_samples = np.random.choice(age_samples, size=2000)[:, np.newaxis]
    kde = KernelDensity(kernel='gaussian', bandwidth=bandwidth).fit(age_samples)

    for ind, lower, upper in ranges:
        sample = kde.sample(len(df))
        range_sample = sample[(sample >= lower) & (sample <= upper)]
        df.loc[df['AGE'] == ind, 'age_sample'] = np.random.choice(range_sample,
                size=(df['AGE'] == ind).sum())

    return df


def add_user_stat(df):
    """Adds traits for the user"""
    df['is_male'] = df['GENDER'] == 1
    df.loc[df["GENDER"] == " ", "GENDER"] = 0
    df.loc[df["AGE"] == " ", "AGE"] = 0
    df.loc[df["CYCLING_LE"] == " ", "CYCLING_LE"] = 0
    df['road_comfortable'] = df['CYCLING_LE'] == 2
    df['traffic_comfortable'] = df['CYCLING_LE'] == 3
    return df


def filter_missing_survey_vals(df):
    """Filters out rows of data without user survey responses

    Filters out rows from the input dataframe where one of the user survey
    responses in the model has no data (has a zero value)
    Many of the users using the app did not fill out the whole user survey.
    As a first approximation of a regression on the full dataset, we can just
    filter out any rows that don't have full data.
    Note that this leaves us with about half the original dataset.
    """
    df = df[(df.AGE != 0) & (df.CYCLING_LE != 0) & (df.GENDER != 0)]
    return df


def clean_data(data, clean_users=True):
    """Cleans the input point speed dataset
    """
    print("Ading bike codes")
    data = add_bike_code(data)
    print("Adding route stats")
    data = add_route_stats(data)
    print("Adding EMME data")
    data = add_emme_stats(data)
    print("Cleaning speed data")
    data.loc[data["SPEED"] < 0, "SPEED"] = 0

    if clean_users:
        print("Adding user stats")
        data = add_user_stat(data)
        print("Performing user age estimate")
        data = estimate_user_age_dist(data, bandwidth=5.0)
        print("Filtering out missing values from user survey")
        #data = filter_missing_survey_vals(data)

    return data


if __name__ == "__main__":
    cached_cleaned = os.path.join(CLEANED_DATA_DIR, "cleaned_data.csv")
    clean_trips(RAW_DATA_DIR, cache_file=cached_cleaned)




