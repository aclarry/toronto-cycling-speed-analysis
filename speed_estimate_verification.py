from collections import defaultdict
import csv
import datetime
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import re
import scipy.stats

EARTH_RADIUS_M = 6371000


def hav(angle):
    """Finds the distance in meters between two lat/lon points
    """
    haversine = math.sin(angle/2)
    return haversine * haversine


def haversine_dist(point1, point2):
    """Finds the distance in meters between two lat/lon points using the haversine function
    parameters:
    point1/point2: A tuple of floats representing lat/lon coordinates
    """
    lat1, lon1 = [deg * math.pi / 180 for deg in point1]
    lat2, lon2 = [deg * math.pi / 180 for deg in point2]
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(hav(lat2 - lat1) + math.cos(lat2) * math.cos(lat1) * hav(lon2 - lon1)))


def read_file(filename):
    with open(filename) as csv_file:
        csv_data = csv.reader(csv_file)
        cleaned_data = [row for row in csv_data if row != []]
        return cleaned_data


def get_data_dict(filename):
    file_data = read_file(filename)
    trips_dict = defaultdict(list)
    for row in file_data[1:]:
        try:
            trip_id = int(row[1])
            row_lon = float(row[3])
            row_lat = float(row[4])
            row_alt = float(row[5])
            row_speed = float(row[6])
            row_hort_acc = float(row[7])
            row_vert_acc = float(row[8])
        except ValueError:
            continue
        try:
            time = datetime.datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
        except:
            time = datetime.datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S.%f")
        trips_dict[trip_id].append({'lat': row_lat, 'lon': row_lon, 'alt': row_alt, 'time': time,
            'speed': row_speed, 'horizontal_acc': row_hort_acc, 'vertical_acc': row_vert_acc})
    for key in trips_dict:
        trips_dict[key].sort(key=lambda x: x['time'])
    return trips_dict


def estimate_point_speed(trip_list, window=1):
    for i in range(window, len(trip_list) - window):
        previous_p = trip_list[i-1]
        next_p = trip_list[i+1]
        distance = haversine_dist((previous_p['lat'], previous_p['lon']),
                                  (next_p['lat'], next_p['lon']))
        trip_list[i]['speed_est'] = distance/(next_p['time'] - previous_p['time']).total_seconds()

    for i in range(0, min(window, len(trip_list))):
        trip_list[i]['speed_est'] = np.nan
        trip_list[-(i+1)]['speed_est'] = np.nan

    return trip_list


def get_point_speed_series(trip_list):
    return (np.array([point['speed_est'] for point in trip_list if not np.isnan(point['speed_est'])]), 
            np.array([point['speed'] for point in trip_list if not np.isnan(point['speed_est'])]))


if __name__ == '__main__':
    window = 2
    if not os.path.exists("speed_estimates_window%d.npy" % window):
        csv_dirname = '/home/andrew/Documents/Work/UofT2016/Bike App Data/Bike Data Original/'
        gps_estimates = np.array([])
        app_estimates = np.array([])
        for filename in os.listdir(csv_dirname):
            if not re.match("^coords-", filename):
                continue
            data_dict = get_data_dict(os.path.join(csv_dirname, filename)) 
            for trip_data in data_dict.values():
                speed_est, speed_act = get_point_speed_series(estimate_point_speed(trip_data, window=window))
                gps_estimates = np.concatenate((gps_estimates, speed_est))
                app_estimates = np.concatenate((app_estimates, speed_act))

        np.save("speed_estimates_window%d" % window, (gps_estimates, app_estimates))
    else:
        gps_estimates, app_estimates = np.load("speed_estimates_window%d.npy" % window)

    app_estimates[app_estimates < 0] = 0
    slope, intercept, r_sq, p_val, stderr = scipy.stats.linregress(app_estimates, gps_estimates)
    print("Solved linear regression:")
    print("GPS estimate = %f * app estimate + %f" % (slope, intercept))
    print("R-squared: %f\tSignificant at the %f level with standard error %f" % (r_sq, p_val, stderr))

    plt.scatter(app_estimates, gps_estimates)
    #plt.hexbin(app_estimates, gps_estimates, bins='log', cmap=plt.cm.Blues)
    plt.xlabel("Speed estimate from app (m/s)")
    plt.ylabel("Speed estimate from GPS data (m/s)")
    #plt.show()
    plt.savefig("plot.png")
    




