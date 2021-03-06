#### Packages to import ###
import pandas as pd
import numpy as np
import pyproj
import datetime
import sys
import os
from sqlalchemy import create_engine
import logging
from twisted.internet import reactor, protocol
from twisted.internet.protocol import DatagramProtocol
import pynmea2
import psycopg2

# Configuration

# Database variables

# table in database to write messages to
tablename = 'gpsReports'

# SQL Alchmey connection string to database.  Documentation here:
# Tested on PostgreSQL, but should support MSSql, Oracle, or SQLlite depending on app needs
# http://docs.sqlalchemy.org/en/latest/dialects/postgresql.html
dbdriver = 'postgresql+psycopg2'
dbuser = 'admin'
dbpass = 'password'
dbserver = 'localhost'
dbport = '5432'
dbname = 'test'
connString = '%s://%s:%s@%s:%s/%s' % (dbdriver,
                                      dbuser, dbpass, dbserver, dbport, dbname)
print connString
engine = create_engine(connString)

# GPS Server port bind.  Send your GPS messages to this port.  Ensure port
# is open on Firewall.
server_listen_port = 10110


### Database Connection and Update Functions ###

def write_to_db(engine, tablename, dataframe):
    # Use pandas and sqlalchemy to insert a dataframe into a database

    try:
        dataframe.to_sql(tablename,
                         engine,
                         index=False,
                         if_exists=u'append',
                         chunksize=100)
        print "inserted into db"
    except:  # IOError as e:
        print "Error in inserting data into db"

###logging function###


def log(msg):
    logging.basicConfig(format='%(asctime)s %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S %p',
                        filename='gpslogfile.log')
    logging.warning(msg)

### Data processing function ###


def read_nmea(source, port, gpgga):
    # Read a pynmea2 object in, the 'gpgga' parameter, and create a pandas
    # dataframe

    format = '%Y-%m-%d %H:%M:%S'
    arrivaltimeUTC = datetime.datetime.utcnow()
    arrivaltimeUTC_t = (
        arrivaltimeUTC - datetime.datetime(1970, 1, 1)).total_seconds()
    today_utc = arrivaltimeUTC.date()
    msgtimeUTC = datetime.datetime.combine(today_utc, gpgga.timestamp)
    msgtimeUTC_t = (msgtimeUTC - datetime.datetime(1970, 1, 1)).total_seconds()
    msgtype = '$GPGGA'
    delta = arrivaltimeUTC_t - msgtimeUTC_t

    values = {'source_n': str(source),
              'source_port': str(port),
              'msgtype': str(msgtype),
              'arrivaltimeUTC': str(arrivaltimeUTC.strftime(format)),
              'arrivaltimeUTC_t': int(arrivaltimeUTC_t),
              'msgtimeUTC': str(msgtimeUTC.strftime(format)),
              'msgtimeUTC_t': int(msgtimeUTC_t),
              'delta': float(delta),
              'lat': float(gpgga.lat),
              'lat_n': str(gpgga.lat_dir),
              'latitude': float(gpgga.latitude),
              'lon': float(gpgga.lon),
              'lon_n': str(gpgga.lon_dir),
              'longitude': float(gpgga.longitude),
              'elevation': float(gpgga.altitude),
              'elevation_unit': str(gpgga.altitude_units)
              }

    # create the dataframe of the message
    dataframe = pd.DataFrame(values, index=[0])
    # typecast the datetime columns as datetimes for database insertion
    dataframe['arrivaltimeUTC'] = pd.to_datetime(dataframe['arrivaltimeUTC'])
    dataframe['msgtimeUTC'] = pd.to_datetime(dataframe['msgtimeUTC'])

    return dataframe

### Transform the coordinates, and insert results into the dataframe###


def transform_coords(dataframe):
    # Add projected coordinates to messages
    coord_sys_n = 'UTM13N'
    coord_sys_n2 = 'NAD83_ID_E_USft'
    wgs84 = pyproj.Proj("+init=EPSG:4326")  # Lat/Lon with WGS84 datum
    UTM13N = pyproj.Proj("+init=EPSG:32613")  # NAD83 UTM zone 13N
    # NAD83 Idaho East (US Feet) for Simplot site
    NAD83_ID_E = pyproj.Proj("+init=EPSG:2241")
    latitude = dataframe['latitude'].values
    longitude = dataframe['longitude'].values
    try:  
        x, y = pyproj.transform(wgs84, UTM13N, longitude, latitude)
        dataframe['coord_sys_n'] = coord_sys_n
    except:
        print "projection error - lat/long are out of bounds for UTM13N!  Assigning X and Y to zero"
        raise
        x, y = 0, 0
        pass

    # Insert the new values into the dataframe
    dataframe['x'] = x
    dataframe['y'] = y
    #dataframe['coord_sys_n']= coord_sys_n
    # Set X and Y values to zero if there was a projection error
    dataframe.fillna(0)

    return dataframe

### Start the GPS Server Listening service ###


class Read_Nmea(DatagramProtocol):
    # Read a UDP packet as an NMEA sentance
    streamReader = pynmea2.NMEAStreamReader()

    def datagramReceived(self, data, (host, port)):
        # A list of the incomming messages before writing to the db
        try:
            for line in data.split('\n'):
                nmea_msg = pynmea2.parse(line + '\n')
                if nmea_msg.sentence_type == 'GGA':  # If message is a GPGGA, write it to the database
                    print "msg to insert: " + str(nmea_msg)
                    log(nmea_msg)
                    try:
                        data_to_insert = transform_coords(
                            read_nmea(host, port, nmea_msg))
                    except:
                        print 'error reading nmea'
                        raise
                        pass
                    try:
                        write_to_db(engine, tablename, data_to_insert)
                    except:
                        print 'error inserting into db!'
                        raise
                        pass
        except:
            print "error parsing message!"
            raise
            pass

reactor.listenUDP(server_listen_port, Read_Nmea())
print 'Im listening for UDP NMEA messages on port %s...' % (server_listen_port)
reactor.run()
