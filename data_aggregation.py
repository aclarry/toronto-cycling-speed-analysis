'''
Created on Jul 16, 2017

@author: Andrew
'''

import os
import xml.etree.ElementTree as ET
import csv
import re
import unicodedata

import arcpy

SPATIAL_REF = arcpy.SpatialReference("WGS 1984")
#SPATIAL_REF = arcpy.SpatialReference("NAD_1983_UTM_Zone_17N")
NETWORK_GDB = r"D:\UofT 2016\Speed Analysis\toronto-cycling-speed-analysis\Data\cycling-network.gdb"
CENTRELINE_INTERSECTION = r"D:\UofT 2016\Bike App Data\Road - Intersections\CENTRELINE_INTERSECTION_simplified.shp"
STOP_SIGNS_FILE = NETWORK_GDB + r"\Centreline_Stopsigns"

def convert_stops_to_shapefile():
    arcpy.env.overwriteOutput = True
    stops_csv = r'D:\UofT 2016\Speed Analysis\toronto-cycling-speed-analysis\Data\Stop Signs (filtered).csv'
    
    arcpy.management.MakeXYEventLayer(stops_csv, "Longitude", "Latitude",
                                      "od", SPATIAL_REF)
    arcpy.conversion.FeatureClassToFeatureClass("od", NETWORK_GDB, "stop_signs")


def pull_stops_to_csv():
    stops_xml = r'D:\UofT 2016\Speed Analysis\toronto-cycling-speed-analysis\Data\Chapter_950\Ch_950_Sch_27_CompulsoryStops.xml'
    stops_csv = r'D:\UofT 2016\Speed Analysis\toronto-cycling-speed-analysis\Data\Stop Signs.csv'
    stops_tree = ET.parse(stops_xml)
    
    with open(stops_csv, 'wb') as stops_file:
        stops_csv = csv.writer(stops_file)
        stops_csv.writerow(("Stop Street", "Cross Street", 
                            "Stop Street Location Details", "Cross Street Location Details",
                            "Has lat/lon coordinates", "Longitude", "Latitude"))
        for num, child in enumerate(stops_tree.findall("Ch_950_Sch_27_CompulsoryStops")):
            try:
                elements = get_intersec_elements(child.find('Intersection').text,
                                                 child.find('Stop_Street_or_Highway').text)
                #print(elements)
                stops_csv.writerow(elements)
            except AttributeError: # The xml element doesn't have one of the attributes (likely 'Stop_Street_or_Highway')
                pass
            #if num > 500:
            #    break
    print("Done pulling stops!")  
    
def get_intersec_elements(intersection_field, stop_street_field):
    try:
        intersection_field = unicodedata.normalize('NFKD', intersection_field)
        intersection_field = intersection_field.decode("windows-1252")
    except TypeError:
        pass
    except UnicodeEncodeError:
        print("Ran into an issue on %s" % (intersection_field))
    try:
        stop_street_field = unicodedata.normalize('NFKD', stop_street_field)
        stop_street_field = stop_street_field.decode("windows-1252")
    except TypeError:
        pass
    except UnicodeEncodeError:
        print("Ran into an issue on %s" % (stop_street_field))
    
    info_regex = re.compile(r'\s*\((.+)\)\s*')
    
    stop_street = info_regex.sub('', stop_street_field)
    if info_regex.search(stop_street_field) is not None:
        stop_street_info = info_regex.search(stop_street_field).groups(0)[0]
    else:
        stop_street_info = ""
        
    cross_street = re.sub(stop_street + r"(\s*\(.*\))?\s*[Aa][Nn][Dd]\s*", '', intersection_field)
    cross_street = re.sub(r"\s*[Aa][Nn][Dd]\s*" + stop_street + r"\s*(\(.*\))?", '', cross_street)
    if info_regex.search(cross_street) is not None:
        cross_street_info = info_regex.search(cross_street).groups(0)[0]
    else:
        cross_street_info = ""
    cross_street = info_regex.sub('', cross_street)
    
    stop_street = stop_names_to_shape_names(stop_street)
    cross_street = stop_names_to_shape_names(cross_street)
    latlon = get_intersection_gps(stop_street, cross_street)
    
    if latlon is None:
        print "Can't find intersection %s - %s :(" % (stop_street, cross_street)
        print intersection_field, stop_street_field
        has_latlon = False
        lat = ""
        lon = ""
    else:
        has_latlon = True
        lat = latlon[0]
        lon = latlon[1]
    return (stop_street, cross_street, stop_street_info, cross_street_info, has_latlon, lon, lat)
    

def stop_names_to_shape_names(street_name):
    
    street_name = re.sub('\s[Rr]oad', ' Rd', street_name)
    street_name = re.sub('\s[Ss]treet', ' St', street_name)
    street_name = re.sub('\s[Aa]venue', ' Ave', street_name)
    street_name = re.sub('\s[Bb]oulevard', ' Blvd', street_name)
    street_name = re.sub('\s[Pp]lace', ' Pl', street_name)
    street_name = re.sub('\s[Cc]ircle', ' Crcl', street_name)
    street_name = re.sub('\s[Dd]rive', ' Dr', street_name)
    street_name = re.sub('\s[Gg]ate$', ' Gt', street_name)
    street_name = re.sub('\s[Cc]rescent$', ' Cres', street_name)
    street_name = re.sub('\s[Cc]ourt$', ' Crt', street_name)
    street_name = re.sub('\s[Gg]rove$', ' Grv', street_name)
    street_name = re.sub('\s[Tt]errace$', ' Ter', street_name)
    street_name = re.sub('\s[Gg]ardens$', ' Gdns', street_name)
    street_name = re.sub('\s[Ss]quare$', ' Sq', street_name)
    street_name = re.sub('\s[Ll]awn$', ' Lwn', street_name)
    street_name = re.sub('\s[Tt]rail', ' Trl', street_name)
    street_name = re.sub('\s[Hh]eights$', ' Hts', street_name)
    street_name = re.sub('\s[Pp]ark$', ' Pk', street_name)
    street_name = re.sub('\s[Pp]arkway$', ' Pkwy', street_name)
    
    street_name = re.sub('[Nn]orth$', 'N', street_name)
    street_name = re.sub('[Ss]outh$', 'S', street_name)
    street_name = re.sub('[Ee]ast$', 'E', street_name)
    street_name = re.sub('[Ww]est$', 'W', street_name)
    
    street_name = re.sub('St\.', 'St', street_name)
    return street_name
    

def get_intersection_gps(stop_street, cross_street):
    stop_street = re.sub("[\.']", "", stop_street)
    cross_street = re.sub("[\.']", "", cross_street)
    stop_street = re.sub("Mc", "Mc%", stop_street)
    cross_street = re.sub("Mc", "Mc%", cross_street)
    stop_street = re.sub("Mac", "Mac%", stop_street)
    cross_street = re.sub("Mac", "Mac%", cross_street)
    if stop_street == cross_street:
        query = "\"INTERSEC5\" = '%s'" % stop_street
    elif "/" in stop_street:
        stop_street1, stop_street2 = stop_street.split("/")[0], stop_street.split("/")[1]
        query = "\"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street1, cross_street, cross_street, stop_street1)
        query += "OR \"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street2, cross_street, cross_street, stop_street2)
    elif "/" in cross_street:
        cross_street1, cross_street2 = cross_street.split("/")[0], cross_street.split("/")[1]
        query = "\"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street, cross_street1, cross_street1, stop_street)
        query += "OR \"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street, cross_street2, cross_street2, stop_street)
    elif " and " in cross_street:
        cross_street1, cross_street2 = cross_street.split(" and ")[0], cross_street.split(" and ")[1]
        query = "\"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street, cross_street1, cross_street1, stop_street)
        query += "OR \"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street, cross_street2, cross_street2, stop_street)
    else:
        query = "\"INTERSEC5\" LIKE '%%%s /%% %s%%' OR \"INTERSEC5\" LIKE '%%%s /%% %s%%'" % (stop_street, cross_street, cross_street, stop_street)
    
    if len(query) > 1000:
        return None
    
    try:
        rows = arcpy.da.SearchCursor(CENTRELINE_INTERSECTION, 
                                     where_clause=query,
                                     field_names=["SHAPE@XY"])
        for row in rows:
            return (row[0][1], row[0][0])
    except RuntimeError:
        print("Hit an error at intersection %s - %s :(" % (stop_street, cross_street))
        raise
    #print(query)
    return None
if __name__ == '__main__':
    pull_stops_to_csv()
    convert_stops_to_shapefile()
    '''
    print(get_intersec_elements("Acheson Boulevard (southern east-west leg) and Acheson Boulevard (north-south leg)", 
                                "Acheson Boulevard (southern east-west leg)"))
    print(get_intersec_elements("Acacia Road and Millwood Road (south intersection)", 
                                "Acacia Road"))
    '''