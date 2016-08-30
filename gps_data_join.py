#!/usr/bin/env python
"""Module for joining route attributes to GPS point data

Author: Andrew Clarry
Date: 14/06/16
"""

import datetime
import multiprocessing
import os
import shutil
import time

import arcpy
import arcgisscripting

gp = arcgisscripting.create(9.3)
arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

ROOT_FOLDER = r"C:\Users\ITSLab\My Documents\Andrew Summer 2016\Sample Route Data"
SPEED_DATA_FOLDER = r"C:\users\ITSLab\My Documents\Andrew Summer 2016\Speed Analysis\Joined Data"

NETWORK_GDB = ROOT_FOLDER + r"\Network_with_Emme\Centreline_withEMME.gdb"
NETWORK_DATASET = NETWORK_GDB + r"\Network\Network_forCS"
CENTRELINE_LINKS = NETWORK_GDB + r"\Network\Links"
SIGNALIZED_INTERSECTION_PATH = NETWORK_GDB + r"\Centreline_JunctionswithSignals"

ACCUMULATORS = ("Meters", "Minutes", "Slope_Time", "High_Slope", "Bike_Attr",
                "Left", "Right", "Intersections", "sCar")


def solve_trip(observed_points, od_points, trip_id, results_folder):
    """Solves an observed route and returns the split result

    Solves a route bounded by a buffer around the observed points, and
    joins the attributes of each edge of the solved route to corresponding
    points from the input GPS data

    parameters
    observed_points: A path to a shapefile containing points of the cyclist's position
    od_points: A path to a shapefile containing just the origin and destination points
    trip_id: The ID of the trip
    results_folder: The path of the folder that output should be put in
    """
    
    print "Create Buffer of 50 meters"
    points_Buffer = ROOT_FOLDER+ r"\Buffer\buffer.gdb\buffer"+trip_id
    points_buffer_line = ROOT_FOLDER+ r"\buffer\buffer.gdb\buffer_line"+trip_id
    arcpy.analysis.Buffer(observed_points, points_Buffer, "50 Meters", "FULL", "ROUND", "ALL", "")
    arcpy.management.PolygonToLine(points_Buffer, points_buffer_line,"IDENTIFY_NEIGHBORS")

    print "Generate Observed Route"
    path_name = "CS_"+trip_id+"_obs"
    NALayer = os.path.join(results_folder, path_name+".lyr")
    arcpy.na.MakeRouteLayer(NETWORK_DATASET, NALayer, "Meters", "USE_INPUT_ORDER", 
            "PRESERVE_BOTH", "NO_TIMEWINDOWS", ACCUMULATORS, "ALLOW_UTURNS", 
            "Oneway", "#", "", "TRUE_LINES_WITH_MEASURES", "")
    arcpy.na.AddLocations(NALayer, "Stops", od_points, "", "5000 Meters", "", 
            "Links SHAPE;Network_forCS_Junctions NONE", "MATCH_TO_CLOSEST", 
            "APPEND", "NO_SNAP", "5 Meters", "INCLUDE", "Links #;Network_forCS_Junctions #")
    arcpy.na.AddLocations(NALayer, "Line Barriers", points_buffer_line, "", 
            "5000 Meters", "", "Links SHAPE;Network_forCS_Junctions NONE", 
            "MATCH_TO_CLOSEST", "APPEND", "NO_SNAP", "5 Meters", "INCLUDE", 
            "Links #;Network_forCS_Junctions #")

    obs_path_name = os.path.join(results_folder, trip_id+"_observed_route.shp")
    try:
        split_route = get_split_solved_route(NALayer, obs_path_name, results_folder, trip_id, 
                copy_id="OBJECTID_12")
    except:
        print "\nObserved route %s could not be solved" % path_name
        with open(os.path.join(SPEED_DATA_FOLDER, "trip_errors.txt"),"a") as file_name:
            file_name.write(str(trip_id)+"\n")
        return
    finally:
        gp.delete_management(NALayer)

    match_route_direction(split_route)
    out_points_name = os.path.join(results_folder, trip_id+"_points.shp")
    arcpy.analysis.SpatialJoin(observed_points, split_route, out_points_name,
                               join_operation="JOIN_ONE_TO_ONE",
                               join_type="KEEP_ALL",
                               match_option="CLOSEST", search_radius="100 Meters")
    add_intersection_distances(out_points_name, split_route, SIGNALIZED_INTERSECTION_PATH)
    out_route_csv = os.path.join(results_folder, trip_id+".csv")
    export_features_to_csv(out_points_name, out_route_csv)


def add_intersection_distances(observed_points, route, junction_file):
    """Adds field indicating distance to the closest signalized intersection"""
    print("Adding intersection data for route %s" % os.path.basename(route))
    route_intersections = os.path.join(os.path.dirname(route), "intersections_tmp.shp")
    arcpy.analysis.SpatialJoin(junction_file, route, route_intersections,
                        join_operation="JOIN_ONE_TO_ONE",
                        join_type="KEEP_COMMON",
                        match_option="WITHIN_A_DISTANCE", search_radius="5 Meters")
    arcpy.analysis.Near(observed_points, route_intersections)
    arcpy.management.Delete(route_intersections)
    arcpy.management.AddField(observed_points, "sig_dist", "DOUBLE")
    arcpy.management.CalculateField(observed_points, "sig_dist",
                                    "!NEAR_DIST!", "PYTHON_9.3")
    

def get_split_solved_route(na_layer, split_route_output, results_folder, trip_id, 
        copy_id="OBJECTID"):
    """Solves a route setup in a network dataset, splits it, and writes it to a file.

    parameters
    na_layer: A string containing the path to the network analysis layer with 
        route information input
    split_route_output: The name of the particular route being solved
    trip_id: The ID of the trip
    copy_id: The name of the index in the dataset used to generate the network
        dataset (the dataset being assumed to be CENTRELINE_LINKS)
    """
    print "Solve and split route"
    try:
        traversed_features = None
        temp_split = ROOT_FOLDER + r"\buffer\buffer.gdb"
        traversed_features = arcpy.na.CopyTraversedSourceFeatures(na_layer, temp_split)
        edges_name, junctions_name, turns_name = [traversed_features.getOutput(i) for i in range(0,3)]
        gp.copyfeatures_management(edges_name, split_route_output)
    finally:
        arcpy.management.Delete(edges_name)
        arcpy.management.Delete(junctions_name)
        arcpy.management.Delete(turns_name)

    arcpy.management.JoinField(split_route_output, "SourceOID", CENTRELINE_LINKS, copy_id)
    return split_route_output


def match_route_direction(route):
    """Adds field to route indicating if edge follows digitization

    Takes a route created by get_split_solved_route, and adds the field
    "link_dir" indicating whether the direction of travel is the same
    as the direction of digitization (1) or the opposite (-1).
    """
    nodes = [{'ID': int(row[0]), 'FNODE': int(row[1]), 'TNODE': int(row[2])}
             for row in arcpy.da.SearchCursor(route, ("FID", "FNODE", "TNODE"))]
    arcpy.management.AddField(route, "link_dir", "SmallInteger")
    if len(nodes) <= 1:
        return
    
    for i in range(0, len(nodes)-1):
        shared_junct = _get_shared_junction(nodes[i]['FNODE'], nodes[i]['TNODE'],
                                            nodes[i+1]['FNODE'], nodes[i+1]['TNODE'])
        if nodes[i]['TNODE'] == shared_junct:
            nodes[i]['link_dir'] = 1
        else: 
            nodes[i]['link_dir'] = -1
    shared_junct = _get_shared_junction(nodes[-1]['FNODE'], nodes[-1]['TNODE'],
                                        nodes[-2]['FNODE'], nodes[-2]['TNODE'])
    if nodes[-1]['FNODE'] == shared_junct:
        nodes[-1]['link_dir'] = 1
    else:
        nodes[-1]['link_dir'] = -1
            
    with arcpy.da.UpdateCursor(route, ("FID", "link_dir")) as cursor:
        for i, row in enumerate(cursor):
            row[1] = nodes[i]['link_dir']
            cursor.updateRow(row)

        
def _get_shared_junction(from_fnode, from_tnode, to_fnode, to_tnode):
    return (set([from_fnode, from_tnode]) & set([to_fnode, to_tnode])).pop()


def export_features_to_csv(split_route, out_csv_name):
    """Saves relevant trip features to a CSV"""
    print("Appending information to route")

    gps_fields = ";".join(("longitude", "latitude", "altitude", "speed", "h_acc",
                           "v_acc", "recorded_a"))
    user_fields = ";".join(("app_user_i", "winter", "rider_hist", "workzip", "income",
                          "cyclingfre", "age", "cycling_le", "gender", "rider_type",
                          "schoolzip", "homezip", "cyclingexp"))
    trip_fields = ";".join(("purpose", "SortID", "Cumul_Mete"))
    road_fields = ";".join(("LF_NAME", "ONE_WAY_DI", "SPD_KM", "sig_dist",
                            "SLOPE_TF", "StreetC_Ev", "Shape_Leng",
                            "Bike_Code", "EMME_MATCH", "EMME_CONTR", "link_dir"))
    fields = ";".join((gps_fields, user_fields, trip_fields, road_fields))
    arcpy.ExportXYv_stats(split_route, fields, "COMMA", out_csv_name, "ADD_FIELD_NAMES") 

def process_date(date):
    """Processes all the trips from a particular date"""
    source_date_folder = os.path.join(ROOT_FOLDER, "Shapefiles", date)
    if not os.path.exists(source_date_folder):
        continue
    arcpy.env.workspace = source_date_folder

    date_folder = os.path.join(SPEED_DATA_FOLDER, date)
    if not os.path.exists(date_folder):
        os.makedirs(date_folder)

    trip_dirs = next(os.walk(source_date_folder))[1]
    for trip_id in trip_dirs:
        if trip_id == "ALL" or trip_id == "OD":
            continue

        trip_folder = os.path.join(source_date_folder, trip_id)
        gp.workspace = trip_folder
        all_points = os.path.join(trip_folder, r"ALL\points_"+trip_id+".shp")
        od_points = os.path.join(trip_folder, r"OD\OD_"+trip_id+".shp")

        print "\nDate: %s, Route %s" % (date, trip_id)
        solve_trip(all_points, od_points, trip_id, date_folder)


if __name__ == '__main__':
    start_time = time.clock()

    num_days = 35
    start_date = datetime.date(2015, 8, 24)
    date_list = [(start_date + datetime.timedelta(days=i)).strftime("%b_%d")
                 for i in range(0, num_days)]

    pool = multiprocessing.Pool()
    pool.map(process_date, date_list)
    pool.close()
    pool.join()
    #for date in date_list:
    #    source_date_folder = os.path.join(ROOT_FOLDER, "Shapefiles", date)
    #    if not os.path.exists(source_date_folder):
    #        continue
    #    arcpy.env.workspace = source_date_folder

    #    date_folder = os.path.join(SPEED_DATA_FOLDER, date)
    #    if not os.path.exists(date_folder):
    #        os.makedirs(date_folder)

    #    trip_dirs = next(os.walk(source_date_folder))[1]
    #    for trip_id in trip_dirs:
    #        if trip_id == "ALL" or trip_id == "OD":
    #            continue

    #        trip_folder = os.path.join(source_date_folder, trip_id)
    #        gp.workspace = trip_folder
    #        all_points = os.path.join(trip_folder, r"ALL\points_"+trip_id+".shp")
    #        od_points = os.path.join(trip_folder, r"OD\OD_"+trip_id+".shp")

    #        print "\nDate: %s, Route %s" % (date, trip_id)
    #        solve_trip(all_points, od_points, trip_id, date_folder)

    print("Program ran for days %s to %s" % (date_list[0], date_list[-1]))
    print("Program ran for %ds" % (time.clock() - start_time))
