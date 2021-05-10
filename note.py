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

configFile='pynote_config.ini'

def loadConfig(configFile):
    config = ConfigParser()
    config.read(configFile)
    if config.has_section('main'):
        return config
    else:
        config.add_section('main')
        with open(configFile, 'w') as f:
            config.write(f)



def getNotesDB(config):
    if config.has_option('main','noteDB'):
        return config.get('main','noteDB')
    else:
        db=input("waar save ons?")
        config.set('main','noteDB',db+'/pynotes.adoc')
        with open(configFile, 'w') as f:
            config.write(f)

        return config.get('main','noteDB')


config= loadConfig(configFile)
DB=getNotesDB(config)
if not os.path.isfile(DB):
    with open(DB, 'w'): pass

def line_prepender(filename, line):
    with open(filename, 'r+') as f:
        content = f.read()
        f.seek(0, 0)
        f.write(line.rstrip('\r\n') + '\n' + content)

date = str(datetime.datetime.now())
line = date+ " " + input("Type the note: ")
line_prepender(DB, line)

# very simple note dumping scrippy. The latest goes to the top. The addded note is prepended
# with the date. The notes live in the DB consants file.
