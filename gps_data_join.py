#!/usr/bin/env python
"""Script for processing CSVs of GPS point data into CSVs matched to route links

Author: Andrew Clarry
Date: 14/06/16
"""

import os
import shutil
import datetime as dt
import traceback

import arcpy
import arcgisscripting


SPATIAL_REF = arcpy.SpatialReference("WGS 1984")
gp = arcgisscripting.create(9.3)
arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

DATA_FOLDER = r"C:\Users\Andrew\Documents\UofT2016\Speed Analysis\toronto-cycling-speed-analysis\Data"
INPUT_DIR = os.path.join(DATA_FOLDER, "Cut Data")
OUTPUT_CSV_FOLDER = os.path.join(DATA_FOLDER, "Geoprocessed Data", "Processed CSVs")
SF_DIR = os.path.join(DATA_FOLDER, "Geoprocessed Data", "Shapefiles")

NETWORK_GDB = r"D:\UofT 2016\Kathryn Choiceset Generation\Network_with_Emme\CalibratedNetworkJuly26\CalibratedNetworkJuly26.gdb"
NETWORK_DATASET = NETWORK_GDB + r"\dataset\dataset_ND"
CENTRELINE_LINKS = NETWORK_GDB + r"\dataset\Calibrated_July26"
SIGNALIZED_INTERSECTION_PATH = NETWORK_GDB + r"\Centreline_JunctionswithSignals"

ACCUMULATORS = ("Meters",)


def solve_trip(observed_points, od_points, trip_id, results_folder, BUFF_SIZE=50):
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
    
    print("Creating %dm buffer" % BUFF_SIZE)
    points_buffer = r"in_memory\buffer"+trip_id
    points_buffer_line = r"in_memory\buffer_line"+trip_id
    arcpy.analysis.Buffer(observed_points, points_buffer, "%d Meters" % BUFF_SIZE,
                          "FULL", "ROUND", "ALL", "")
    arcpy.management.PolygonToLine(points_buffer, points_buffer_line,"IDENTIFY_NEIGHBORS")

    print("Generating observed route")
    path_name = "CS_"+trip_id+"_obs"
    NALayer = os.path.join(SF_DIR, path_name+".lyr")
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

    obs_path_name = os.path.join(SF_DIR, trip_id+"_observed_route.shp")
    try:
        split_route = get_split_solved_route(NALayer, obs_path_name, results_folder, trip_id, 
                copy_id="OBJECTID_12")
    except:
        if BUFF_SIZE == 50:
            solve_trip(observed_points, od_points, trip_id, results_folder, BUFF_SIZE=100)
            return
        print "ERROR: Observed route %s could not be solved" % path_name
        return
    finally:
        arcpy.management.Delete(NALayer)
        arcpy.management.Delete(points_buffer)
        arcpy.management.Delete(points_buffer_line)

    try:
        match_route_direction(split_route)
    except KeyError:
        return
    
    out_points_name = os.path.join(SF_DIR, trip_id+"_points.shp")
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
    arcpy.analysis.Near(observed_points, route_intersections, method="GEODESIC")
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
        temp_split = "in_memory"
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

    gps_fields = ";".join(("longitude", "latitude", "altitude", "speed", "hort_accur",
                           "vert_accur", "started_at", "recorded_a"))
    user_fields = ";".join(("app_user_i", "winter", "rider_hist", "workzip", "income",
                          "cyclingfre", "age", "cycling_le", "gender", "rider_type",
                          "schoolzip", "homezip", "cyclingexp"))
    trip_fields = ";".join(("purpose", "FID", "Cumul_Mete"))
    road_fields = ";".join(("LF_NAME", "ONE_WAY_DI", "sig_dist", "SourceOID",
                            "SLOPE_TF", "Shape_Leng", "RDCLASS", "Bike_Class",
                            "Bike_Code", "EMME_MATCH", "EMME_CONTR", "link_dir"))
    fields = ";".join((gps_fields, user_fields, trip_fields, road_fields))
    arcpy.ExportXYv_stats(split_route, fields, "COMMA", out_csv_name, "ADD_FIELD_NAMES") 


def csv_to_shapefiles(trip_id):
    "Converts an input CSV file into shapefiles of all points and origin-destination points"
    all_csv = os.path.join(INPUT_DIR, "%s.csv" %trip_id)
    od_csv = os.path.join(INPUT_DIR, "%s_od.csv" %trip_id) 
    all_name = "ALL_%s.shp" % trip_id
    od_name = "OD_%s.shp" % trip_id

    arcpy.management.MakeXYEventLayer(all_csv, "longitude", "latitude",
                                      "all", SPATIAL_REF, "altitude")
    try:
        arcpy.conversion.FeatureClassToFeatureClass("all", SF_DIR, all_name)
    except arcpy.ExecuteError:
        print("file %s already exists" % os.path.join(SF_DIR, all_name))

    arcpy.management.MakeXYEventLayer(od_csv, "longitude", "latitude",
                                      "od", SPATIAL_REF, "altitude")
    try:
        arcpy.conversion.FeatureClassToFeatureClass("od", SF_DIR, od_name)
    except arcpy.ExecuteError:
        print("file %s already exists" % os.path.join(SF_DIR, od_name))
    
    return os.path.join(SF_DIR, all_name), os.path.join(SF_DIR, od_name)


if __name__ == '__main__':

    start_t = dt.datetime.now()

    trip_ids = set([os.path.splitext(f)[0] for f in os.listdir(INPUT_DIR) if not "_od.csv" in f])
    print("Beginning to process %d trips from %s" % (len(trip_ids), INPUT_DIR))
    for i, trip_id in enumerate(trip_ids):
        print("\nProcessing trip %s" % trip_id)
        try:
            all_points, od_points = csv_to_shapefiles(trip_id)
            solve_trip(all_points, od_points, trip_id, OUTPUT_CSV_FOLDER)
        except:
            print("ERROR: Trip %s could not be processed" % trip_id)
            traceback.print_exc()
        
        if (i + 1) % 10 == 0:
            print("Script has processed %d trips for %ds"
                  % (i + 1, (dt.datetime.now() - start_t).total_seconds()))

    print("\n\nSuccessfully finished processing trips")
    print("Job took %ds" % (dt.datetime.now() - start_t).total_seconds())

