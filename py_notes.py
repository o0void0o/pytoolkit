# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import datetime
import os.path
from configparser import ConfigParser

# very simple note dumping script. The latest note goes to the top. The addded note is prepended
# with the current date.

# constants
configFile = 'pynote_config.ini'
version = '1'
dbFileName = '/pynotes.adoc'

# functions
def saveConfig(config):
     with open(configFile, 'w') as f:
            config.write(f)

def createCleanConfig(config):
    config.add_section('main')
    config.set('main','version',version)
    saveConfig(config)
       
def loadConfig(configFile):
    config = ConfigParser()
    config.read(configFile)
    if not config.has_section('main'):
        createCleanConfig(config)
    return config       

def getNotesDB(config):
    if not config.has_option('main','note_db_path'):
        savePath=input("Please enter path to save notes in: ")
        config.set('main','note_db_path',savePath + dbFileName)
        saveConfig(config)
    
    note_db = config.get('main','note_db_path')
    # creates a note database if it doesn't all ready exists.
    if not os.path.isfile(note_db):
        with open(note_db, 'w'): pass
    
    return note_db

def line_prepender(filename, line):
    with open(filename, 'r+') as f:
        content = f.read()
        f.seek(0, 0)
        f.write(line.rstrip('\r\n') + '\n' + content)

# script starts here
config = loadConfig(configFile)
note_db = getNotesDB(config)
date = str(datetime.datetime.now())
line = date+ " " + input("Type the note: ")
line_prepender(note_db, line)